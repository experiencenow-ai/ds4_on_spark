#!/usr/bin/env python3
"""Build a ds4-mtp-slowpath-v1 report from antirez/ds4 MTP logs."""

from __future__ import annotations

import hashlib
import json
import sys
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import extract_antirez_ds4_mtp_conf_log as mtp_extract


REQUIRED_COMPONENTS = (
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

BLOCKER_BY_COMPONENT = {
	"verifier_replay_ms": "verifier_replay_overhead",
	"draft_eval_ms": "draft_eval_overhead",
	"target_eval_ms": "target_verifier_overhead",
	"output_head_ms": "output_head_overhead",
	"cache_sync_ms": "cache_sync_overhead",
	"cuda_sync_ms": "cuda_sync_overhead",
	"logging_ms": "logging_overhead",
	"capture_ms": "capture_overhead",
	"token_commit_ms": "token_commit_overhead",
	"scheduler_overhead_ms": "scheduler_overhead",
}


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
	s = str(raw).strip()
	if s == "" or s.upper() == "NA":
		return None
	try:
		return float(s)
	except ValueError:
		return None


def _int_or_zero(raw: object) -> int:
	if isinstance(raw, int):
		return int(raw)
	if isinstance(raw, float) and float(int(raw)) == float(raw):
		return int(raw)
	try:
		return int(str(raw).strip(), 10)
	except (TypeError, ValueError):
		return 0


def _read_kv_file(path: Path) -> dict[str, str]:
	kv: dict[str, str] = {}
	if str(path) == "" or not path.exists():
		return kv
	for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
		line = raw.strip()
		if "=" not in line:
			continue
		k, v = line.split("=", 1)
		kv[k.strip()] = v.strip()
	return kv


def _baseline_tps_from_summary(path: Optional[Path]) -> Optional[float]:
	if path is None:
		return None
	kv = _read_kv_file(path)
	return _float_or_none(kv.get("generation_tps", kv.get("decode_tps")))


def _prompt_hash(prompt: str, explicit_hash: str) -> str:
	if explicit_hash.strip() != "":
		return explicit_hash.strip()
	return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _components(raw: dict[str, Any]) -> dict[str, float]:
	out = {k: 0.0 for k in REQUIRED_COMPONENTS}
	for k, v in (raw or {}).items():
		if k in out:
			out[k] = float(_float_or_none(v) or 0.0)
	return out


def _slowest_component(components: dict[str, float], fallback: object) -> Optional[str]:
	fb = str(fallback or "").strip()
	if fb in components and float(components.get(fb, 0.0)) > 0.0:
		return fb
	best = max(components.items(), key=lambda kv: float(kv[1]))[0]
	return best if float(components.get(best, 0.0)) > 0.0 else None


def _blocker(
	*,
	baseline_generation_tps: Optional[float],
	mtp_generation_tps: Optional[float],
	speedup_vs_baseline: Optional[float],
	mtp_draft: int,
	attempted_draft_tokens: int,
	slowest_component: Optional[str],
	components: dict[str, float],
) -> tuple[str, str]:
	if baseline_generation_tps is None or mtp_generation_tps is None:
		return (
			"missing_measurement",
			"baseline_generation_tps and mtp_generation_tps are both required before claiming a speed result",
		)
	if int(mtp_draft) <= 1 and int(attempted_draft_tokens) == 0:
		return (
			"no_speculative_suffix",
			"ds4 --mtp-draft <= 1 accepts only the target token and does not enter the multi-token speculative suffix path",
		)
	if speedup_vs_baseline is not None and float(speedup_vs_baseline) > 1.0:
		return ("none", "MTP generation throughput is above baseline on this controlled comparison")
	if slowest_component is None:
		return (
			"missing_slowpath_timing",
			"MTP is not faster than baseline, but no DS4_MTP_TIMING component lines were captured",
		)
	kind = BLOCKER_BY_COMPONENT.get(slowest_component, "unknown_slowpath_component")
	return (
		kind,
		"MTP %.6f t/s <= baseline %.6f t/s; slowest_component=%s %.3f ms" % (
			float(mtp_generation_tps),
			float(baseline_generation_tps),
			slowest_component,
			float(components.get(slowest_component, 0.0)),
		),
	)


def build_report_from_lines(
	lines: Iterable[str],
	*,
	run_id: str,
	model_id: str,
	runtime_id: str,
	prompt: str,
	prompt_hash: str,
	mtp_draft: int,
	mtp_margin: float,
	baseline_generation_tps: Optional[float],
	mtp_generation_tps_override: Optional[float] = None,
) -> dict[str, Any]:
	extracted = mtp_extract.extract_events(list(lines))
	totals = extracted.get("totals") or {}
	speed = extracted.get("speed") or {}
	mismatches = extracted.get("mismatches") or {}
	timing = extracted.get("timing") or {}
	counts = timing.get("call_counts") or {}
	extract_counts = extracted.get("counts") or {}
	accepted_tokens = _int_or_zero(totals.get("draft_tokens_accepted_est"))
	attempted_draft_tokens = _int_or_zero(totals.get("draft_tokens_attempted_est"))
	accept_rate = None
	if attempted_draft_tokens > 0:
		accept_rate = float(accepted_tokens) / float(attempted_draft_tokens)
	mtp_generation_tps = mtp_generation_tps_override
	if mtp_generation_tps is None:
		mtp_generation_tps = _float_or_none(speed.get("generation_tps"))
	speedup_vs_baseline = None
	if baseline_generation_tps is not None and mtp_generation_tps is not None and baseline_generation_tps > 0.0:
		speedup_vs_baseline = float(mtp_generation_tps) / float(baseline_generation_tps)
	per_component_ms = _components(timing.get("per_component_ms") or {})
	slowest_component = _slowest_component(per_component_ms, timing.get("slowest_component"))
	target_next_mismatch_events = _int_or_zero(mismatches.get("target_next_mismatch_events"))
	verifier_ms = float(_float_or_none(timing.get("verifier_ms")) or per_component_ms["target_eval_ms"])
	logging_capture_ms = per_component_ms["logging_ms"] + per_component_ms["capture_ms"]
	emitted_tokens = _int_or_zero(timing.get("emitted_tokens"))
	if emitted_tokens == 0:
		emitted_tokens = int(accepted_tokens) + _int_or_zero(extract_counts.get("conf_events")) + _int_or_zero(extract_counts.get("miss_first_events"))
	target_eval_per_emitted = None
	if emitted_tokens > 0:
		target_eval_per_emitted = per_component_ms["target_eval_ms"] / float(emitted_tokens)
	target_eval_per_accepted = None
	if accepted_tokens > 0:
		target_eval_per_accepted = per_component_ms["target_eval_ms"] / float(accepted_tokens)
	blocker_kind, blocker_detail = _blocker(
		baseline_generation_tps=baseline_generation_tps,
		mtp_generation_tps=mtp_generation_tps,
		speedup_vs_baseline=speedup_vs_baseline,
		mtp_draft=int(mtp_draft),
		attempted_draft_tokens=int(attempted_draft_tokens),
		slowest_component=slowest_component,
		components=per_component_ms,
	)
	return {
		"format": "ds4-mtp-slowpath-v1",
		"run_id": run_id,
		"model_id": model_id,
		"runtime_id": runtime_id,
		"prompt_hash": _prompt_hash(prompt, prompt_hash),
		"mtp_draft": int(mtp_draft),
		"mtp_margin": float(mtp_margin),
		"accepted_tokens": int(accepted_tokens),
		"attempted_draft_tokens": int(attempted_draft_tokens),
		"draft_tokens_accepted": int(accepted_tokens),
		"draft_tokens_attempted": int(attempted_draft_tokens),
		"accept_rate": accept_rate,
		"baseline_generation_tps": baseline_generation_tps,
		"mtp_generation_tps": mtp_generation_tps,
		"speedup_vs_baseline": speedup_vs_baseline,
		"target_next_mismatch_count": target_next_mismatch_events,
		"target_next_mismatch_events": target_next_mismatch_events,
		"slowest_component": slowest_component,
		"per_component_ms": per_component_ms,
		"verifier_replay_ms": per_component_ms["verifier_replay_ms"],
		"verifier_ms": verifier_ms,
		"draft_eval_ms": per_component_ms["draft_eval_ms"],
		"target_eval_ms": per_component_ms["target_eval_ms"],
		"output_head_ms": per_component_ms["output_head_ms"],
		"cache_sync_ms": per_component_ms["cache_sync_ms"],
		"cuda_sync_ms": per_component_ms["cuda_sync_ms"],
		"logging_ms": per_component_ms["logging_ms"],
		"capture_ms": per_component_ms["capture_ms"],
		"logging_capture_ms": logging_capture_ms,
		"token_commit_ms": per_component_ms["token_commit_ms"],
		"scheduler_overhead_ms": per_component_ms["scheduler_overhead_ms"],
		"target_eval_call_count": _int_or_zero(counts.get("target_eval_call_count")),
		"draft_eval_call_count": _int_or_zero(counts.get("draft_eval_call_count")),
		"output_head_call_count": _int_or_zero(counts.get("output_head_call_count")),
		"verifier_replay_count": _int_or_zero(counts.get("verifier_replay_count")),
		"cache_rewind_count": _int_or_zero(counts.get("cache_rewind_count")),
		"cache_sync_count": _int_or_zero(counts.get("cache_sync_count")),
		"cuda_sync_count": _int_or_zero(counts.get("cuda_sync_count")),
		"emitted_tokens": int(emitted_tokens),
		"target_eval_ms_per_emitted_token": target_eval_per_emitted,
		"target_eval_ms_per_accepted_draft_token": target_eval_per_accepted,
		"blocker_kind": blocker_kind,
		"blocker_detail": blocker_detail,
		"timing_event_count": _int_or_zero(timing.get("events")),
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--mtp-log", action="append", default=[], help="MTP stdout/stderr log path (repeatable).")
	ap.add_argument("--baseline-summary", default="", help="Baseline summary key=value file.")
	ap.add_argument("--baseline-generation-tps", type=float, default=None)
	ap.add_argument("--mtp-generation-tps", type=float, default=None)
	ap.add_argument("--run-id", default="")
	ap.add_argument("--model-id", default="DeepSeek-V4-Flash-IQ2XXS-chat-v2")
	ap.add_argument("--runtime-id", default="antirez/ds4@3630e64+cuda-mtp")
	ap.add_argument("--prompt", default="")
	ap.add_argument("--prompt-hash", default="")
	ap.add_argument("--mtp-draft", type=int, default=0)
	ap.add_argument("--mtp-margin", type=float, default=0.0)
	ap.add_argument("--out-json", default="")
	args = ap.parse_args(argv)

	logs = [Path(p) for p in args.mtp_log]
	if len(logs) == 0:
		raise SystemExit("at least one --mtp-log is required")
	baseline_generation_tps = args.baseline_generation_tps
	if baseline_generation_tps is None and str(args.baseline_summary).strip() != "":
		baseline_generation_tps = _baseline_tps_from_summary(Path(str(args.baseline_summary)))
	run_id = str(args.run_id).strip()
	if run_id == "":
		run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
	report = build_report_from_lines(
		_iter_lines(logs),
		run_id=run_id,
		model_id=str(args.model_id),
		runtime_id=str(args.runtime_id),
		prompt=str(args.prompt),
		prompt_hash=str(args.prompt_hash),
		mtp_draft=int(args.mtp_draft),
		mtp_margin=float(args.mtp_margin),
		baseline_generation_tps=baseline_generation_tps,
		mtp_generation_tps_override=args.mtp_generation_tps,
	)
	text = json.dumps(report, indent=2, sort_keys=True) + "\n"
	if str(args.out_json).strip() != "":
		Path(str(args.out_json)).write_text(text, encoding="utf-8")
	print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
