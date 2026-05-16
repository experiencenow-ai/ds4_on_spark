#!/usr/bin/env python3
"""Build ds4-mtp-verifier-economics-v1 from DS4 MTP timing logs."""

from __future__ import annotations

import hashlib
import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import extract_antirez_ds4_mtp_conf_log as mtp_extract


FORMAT = "ds4-mtp-verifier-economics-v1"


def _iter_lines(paths: list[Path]) -> Iterable[str]:
	for path in paths:
		with path.open("r", encoding="utf-8", errors="replace") as f:
			for line in f:
				yield line.rstrip("\n")


def _float_or_none(raw: object) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def _int(raw: object) -> int:
	if isinstance(raw, int):
		return int(raw)
	if isinstance(raw, float) and float(int(raw)) == float(raw):
		return int(raw)
	try:
		return int(str(raw).strip(), 10)
	except (TypeError, ValueError):
		return 0


def _prompt_hash(prompt: str, explicit_hash: str) -> str:
	if explicit_hash.strip() != "":
		return explicit_hash.strip()
	return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _component(components: dict[str, Any], key: str) -> float:
	return float(_float_or_none(components.get(key)) or 0.0)


def _accounted_timing_ms(timing: dict[str, Any], components: dict[str, Any]) -> float:
	total = _float_or_none(timing.get("total_reported_ms"))
	if total is not None and total > 0.0:
		return float(total)
	return sum(
		_component(components, key)
		for key in (
			"verifier_replay_ms",
			"draft_eval_ms",
			"target_eval_ms",
			"output_head_ms",
			"cache_sync_ms",
			"cuda_sync_ms",
			"logging_ms",
			"capture_ms",
			"token_commit_ms",
			"scheduler_overhead_ms",
		)
	)


def _generation_wall_ms(emitted_tokens: int, mtp_tps: Optional[float]) -> Optional[float]:
	if emitted_tokens <= 0 or mtp_tps is None or float(mtp_tps) <= 0.0:
		return None
	return (float(emitted_tokens) / float(mtp_tps)) * 1000.0


def _decode2_row_economics(kinds: dict[str, Any], invocations: int, output_head_calls: int) -> tuple[int, int, int]:
	decode2_events = _int(kinds.get("decode2"))
	if decode2_events <= 0:
		return (output_head_calls, output_head_calls, 0)
	full_vocab_rows = decode2_events
	top1_rows = decode2_events
	other_head_rows = max(0, output_head_calls - (2 * decode2_events))
	return (output_head_calls, full_vocab_rows + other_head_rows, top1_rows)


def build_report_from_lines(
	lines: Iterable[str],
	*,
	run_id: str,
	model_id: str,
	runtime_id: str,
	prompt: str,
	prompt_hash: str,
	baseline_tps: float,
	mtp_tps: Optional[float],
) -> dict[str, Any]:
	extracted = mtp_extract.extract_events(list(lines))
	totals = extracted.get("totals") or {}
	speed = extracted.get("speed") or {}
	timing = extracted.get("timing") or {}
	components = timing.get("per_component_ms") or {}
	counts = timing.get("call_counts") or {}
	kinds = timing.get("kinds") or {}
	accepted = _int(totals.get("draft_tokens_accepted_est"))
	attempted = _int(totals.get("draft_tokens_attempted_est"))
	accept_rate = (float(accepted) / float(attempted)) if attempted > 0 else None
	if mtp_tps is None:
		mtp_tps = _float_or_none(speed.get("generation_tps"))
	speedup = (float(mtp_tps) / float(baseline_tps)) if mtp_tps is not None and baseline_tps > 0.0 else None
	invocations = _int(counts.get("target_verifier_invocation_count"))
	if invocations <= 0:
		invocations = _int(timing.get("events"))
	target_positions = _int(counts.get("target_positions_verified"))
	if target_positions <= 0:
		target_positions = _int(counts.get("target_eval_call_count"))
	output_head_calls = _int(counts.get("output_head_call_count"))
	output_head_rows = _int(counts.get("output_head_rows"))
	full_vocab_rows = _int(counts.get("full_vocab_logits_rows"))
	top1_rows = _int(counts.get("top1_only_rows"))
	if output_head_rows == 0 and full_vocab_rows == 0 and top1_rows == 0:
		output_head_rows, full_vocab_rows, top1_rows = _decode2_row_economics(kinds, invocations, output_head_calls)
	target_eval_ms = _component(components, "target_eval_ms")
	output_head_ms = _component(components, "output_head_ms")
	emitted_tokens = _int(timing.get("emitted_tokens"))
	generation_wall_ms_est = _generation_wall_ms(emitted_tokens, mtp_tps)
	accounted_timing_ms = _accounted_timing_ms(timing, components)
	unaccounted_wall_ms = None
	timing_coverage_rate = None
	if generation_wall_ms_est is not None and generation_wall_ms_est > 0.0:
		unaccounted_wall_ms = max(0.0, float(generation_wall_ms_est) - accounted_timing_ms)
		timing_coverage_rate = accounted_timing_ms / float(generation_wall_ms_est)
	slowest = str(timing.get("slowest_component") or "")
	if slowest == "":
		slowest = max(((k, _component(components, k)) for k in components), key=lambda kv: kv[1])[0] if components else ""
	blocker = "none"
	blocker_detail = ""
	if mtp_tps is None or speedup is None:
		blocker = "missing_measurement"
		blocker_detail = "baseline_tps and mtp_tps are required to judge verifier economics"
	elif mtp_tps <= baseline_tps:
		if timing_coverage_rate is not None and timing_coverage_rate < 0.5:
			blocker = "unaccounted_generation_wall_time"
			blocker_detail = (
				"MTP %.6f t/s <= baseline %.6f t/s; timing coverage=%.6f accounted_ms=%.3f "
				"generation_wall_ms_est=%.3f unaccounted_ms=%.3f"
				% (
					float(mtp_tps),
					float(baseline_tps),
					float(timing_coverage_rate),
					float(accounted_timing_ms),
					float(generation_wall_ms_est),
					float(unaccounted_wall_ms or 0.0),
				)
			)
		elif invocations > 0 and target_positions > invocations and output_head_calls < target_positions and slowest == "target_eval_ms":
			blocker = "target_verifier_overhead"
			blocker_detail = (
				"MTP %.6f t/s <= baseline %.6f t/s; verifier invocations=%d target_positions=%d output_head_invocations=%d"
				% (float(mtp_tps), float(baseline_tps), invocations, target_positions, output_head_calls)
			)
		elif output_head_calls > 0 and output_head_calls < target_positions and slowest == "target_eval_ms":
			blocker = "target_suffix_verifier_still_serial"
			blocker_detail = (
				"MTP %.6f t/s <= baseline %.6f t/s; verifier invocations=%d target_positions=%d output_head_invocations=%d"
				% (float(mtp_tps), float(baseline_tps), invocations, target_positions, output_head_calls)
			)
		else:
			blocker = "target_output_head_token_for_token"
			blocker_detail = (
				"MTP %.6f t/s <= baseline %.6f t/s; verifier invocations=%d target_positions=%d output_head_invocations=%d"
				% (float(mtp_tps), float(baseline_tps), invocations, target_positions, output_head_calls)
			)
	return {
		"format": FORMAT,
		"run_id": run_id,
		"model_id": model_id,
		"runtime_id": runtime_id,
		"prompt_hash": _prompt_hash(prompt, prompt_hash),
		"baseline_tps": float(baseline_tps),
		"mtp_tps": mtp_tps,
		"speedup_vs_baseline": speedup,
		"accepted_draft_tokens": accepted,
		"attempted_draft_tokens": attempted,
		"accept_rate": accept_rate,
		"emitted_tokens": emitted_tokens,
		"generation_wall_ms_est": generation_wall_ms_est,
		"accounted_timing_ms": accounted_timing_ms,
		"unaccounted_generation_wall_ms": unaccounted_wall_ms,
		"timing_coverage_rate": timing_coverage_rate,
		"target_verifier_invocation_count": invocations,
		"target_positions_verified": target_positions,
		"target_positions_per_invocation": (float(target_positions) / float(invocations)) if invocations > 0 else None,
		"target_eval_ms": target_eval_ms,
		"target_eval_ms_per_invocation": (target_eval_ms / float(invocations)) if invocations > 0 else None,
		"target_eval_ms_per_verified_position": (target_eval_ms / float(target_positions)) if target_positions > 0 else None,
		"output_head_invocation_count": output_head_calls,
		"output_head_rows": output_head_rows,
		"full_vocab_logits_rows": full_vocab_rows,
		"top1_only_rows": top1_rows,
		"draft_eval_ms": _component(components, "draft_eval_ms"),
		"snapshot_ms": _component(components, "capture_ms"),
		"kv_commit_ms": _component(components, "token_commit_ms"),
		"kv_restore_ms": _component(components, "verifier_replay_ms"),
		"logits_readback_ms": _component(components, "logging_ms"),
		"token_commit_ms": _component(components, "token_commit_ms"),
		"output_head_ms": output_head_ms,
		"cache_sync_count": _int(counts.get("cache_sync_count")),
		"target_next_mismatch_events": _int((extracted.get("mismatches") or {}).get("target_next_mismatch_events")),
		"slowest_component": slowest,
		"blocker_kind": blocker,
		"blocker_detail": blocker_detail,
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--mtp-log", action="append", default=[], required=True)
	ap.add_argument("--baseline-tps", required=True, type=float)
	ap.add_argument("--mtp-tps", type=float, default=None)
	ap.add_argument("--run-id", required=True)
	ap.add_argument("--model-id", default="DeepSeek-V4-Flash-IQ2XXS-chat-v2")
	ap.add_argument("--runtime-id", default="antirez/ds4@3630e64+cuda-mtp")
	ap.add_argument("--prompt", default="")
	ap.add_argument("--prompt-hash", default="")
	ap.add_argument("--out-json", default="")
	args = ap.parse_args(argv)
	report = build_report_from_lines(
		_iter_lines([Path(p) for p in args.mtp_log]),
		run_id=str(args.run_id),
		model_id=str(args.model_id),
		runtime_id=str(args.runtime_id),
		prompt=str(args.prompt),
		prompt_hash=str(args.prompt_hash),
		baseline_tps=float(args.baseline_tps),
		mtp_tps=args.mtp_tps,
	)
	text = json.dumps(report, indent=2, sort_keys=True) + "\n"
	if str(args.out_json).strip() != "":
		Path(str(args.out_json)).write_text(text, encoding="utf-8")
	print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
