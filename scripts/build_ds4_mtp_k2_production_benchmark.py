#!/usr/bin/env python3
"""Build ds4-mtp-k2-production-benchmark-v1 artifacts from paired logs."""

from __future__ import annotations

import hashlib
import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import extract_antirez_ds4_mtp_conf_log as extract
from scripts import validate_ds4_mtp_k2_production_benchmark as validate


def _iter_lines(paths: list[Path]) -> Iterable[str]:
	for path in paths:
		with path.open("r", encoding="utf-8", errors="replace") as f:
			for line in f:
				yield line.rstrip("\n")


def _sha256_text(text: str) -> str:
	return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _last_bench_value(obj: dict[str, Any], key: str) -> Any:
	for ev in reversed((((obj.get("benchmark") or {}).get("events")) or [])):
		if key in ev:
			return ev.get(key)
	return None


def _float(raw: Any, default: float = 0.0) -> float:
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw))
	except (TypeError, ValueError):
		return float(default)


def _int(raw: Any, default: int = 0) -> int:
	if isinstance(raw, int):
		return int(raw)
	if isinstance(raw, float) and float(int(raw)) == float(raw):
		return int(raw)
	try:
		return int(str(raw), 10)
	except (TypeError, ValueError):
		return int(default)


def _tail_case(n_predict: int) -> str:
	return f"n_predict_mod_3_{int(n_predict) % 3}"


def build_artifact(
	baseline_logs: list[Path],
	mtp_logs: list[Path],
	*,
	run_id: str,
	model_id: str,
	runtime_id: str,
	quantization_id: str,
	prompt_id: str,
	prompt: str,
	prompt_hash: str,
	n_predict: int,
	stdout_suppressed: bool,
	suppress_output_mode: str,
	tail_acceptance_status: str,
	benchmark_matrix_status: str,
) -> dict[str, Any]:
	base = extract.extract_events(list(_iter_lines(baseline_logs)))
	mtp = extract.extract_events(list(_iter_lines(mtp_logs)))
	base_tps = _float((base.get("speed") or {}).get("generation_tps"))
	mtp_tps = _float((mtp.get("speed") or {}).get("generation_tps"))
	totals = mtp.get("totals") or {}
	timing = mtp.get("timing") or {}
	counts = timing.get("call_counts") or {}
	attempted = _int(totals.get("draft_tokens_attempted_est"))
	accepted = _int(totals.get("draft_tokens_accepted_est"))
	mismatch = _int((mtp.get("mismatches") or {}).get("target_next_mismatch_events"))
	verifier_calls = _int(counts.get("target_verifier_invocation_count"))
	target_positions = _int(counts.get("target_positions_verified"))
	head_calls = _int(counts.get("output_head_call_count"))
	full_vocab_rows = _int(counts.get("full_vocab_logits_rows"))
	top1_rows = _int(counts.get("top1_only_rows"))
	blockers: list[str] = []
	blocker_kind = "none"
	blocker_detail = ""
	if base_tps <= 0.0 or mtp_tps <= 0.0:
		blockers.append("missing_comparable_tps")
		blocker_kind = "benchmark_not_comparable"
	if mismatch != 0:
		blockers.append("target_next_mismatch")
		blocker_kind = "target_next_mismatch"
	if tail_acceptance_status != "passed":
		blockers.append("tail_verifier_not_validated")
		blocker_kind = "tail_verifier_not_validated"
	if benchmark_matrix_status != "passed":
		blockers.append("benchmark_matrix_not_complete")
	if blockers:
		blocker_detail = "; ".join(blockers)
	return {
		"format": validate.FORMAT,
		"run_id": run_id,
		"model_id": model_id,
		"runtime_id": runtime_id,
		"quantization_id": quantization_id,
		"prompt_id": prompt_id,
		"prompt_hash": prompt_hash if prompt_hash else _sha256_text(prompt),
		"prompt_shape": str(_last_bench_value(mtp, "prompt_shape") or ""),
		"n_predict": int(n_predict),
		"baseline_tps": base_tps,
		"mtp_tps": mtp_tps,
		"speedup_vs_baseline": (mtp_tps / base_tps) if base_tps > 0.0 else 0.0,
		"accepted_draft_tokens": accepted,
		"attempted_draft_tokens": attempted,
		"accept_rate": (float(accepted) / float(attempted)) if attempted > 0 else 0.0,
		"target_next_mismatch_events": mismatch,
		"verifier_invocation_count": verifier_calls,
		"target_positions_verified": target_positions,
		"target_positions_per_invocation": (float(target_positions) / float(verifier_calls)) if verifier_calls > 0 else 0.0,
		"output_head_invocation_count": head_calls,
		"full_vocab_logits_rows": full_vocab_rows,
		"top1_only_rows": top1_rows,
		"tail_case": _tail_case(int(n_predict)),
		"tail_acceptance_status": tail_acceptance_status,
		"stdout_suppressed": bool(stdout_suppressed),
		"suppress_output_mode": suppress_output_mode,
		"benchmark_matrix_status": benchmark_matrix_status,
		"production_eligible": bool(not blockers),
		"production_blockers": blockers,
		"blocker_kind": blocker_kind,
		"blocker_detail": blocker_detail,
	}


def main() -> int:
	ap = ArgumentParser()
	ap.add_argument("--baseline-log", action="append", required=True, default=[])
	ap.add_argument("--mtp-log", action="append", required=True, default=[])
	ap.add_argument("--run-id", required=True)
	ap.add_argument("--model-id", default="DeepSeek-V4-Flash-IQ2XXS-chat-v2")
	ap.add_argument("--runtime-id", default="antirez/ds4@3630e64+cuda-mtp-k2")
	ap.add_argument("--quantization-id", default="DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf")
	ap.add_argument("--prompt-id", required=True)
	ap.add_argument("--prompt", default="")
	ap.add_argument("--prompt-hash", default="")
	ap.add_argument("--n-predict", type=int, required=True)
	ap.add_argument("--stdout-suppressed", action="store_true")
	ap.add_argument("--suppress-output-mode", default="stdout")
	ap.add_argument("--tail-acceptance-status", choices=sorted(validate.TAIL_STATUSES), default="not_run")
	ap.add_argument("--benchmark-matrix-status", default="not_complete")
	ap.add_argument("--out-json", default="")
	args = ap.parse_args()
	artifact = build_artifact(
		[Path(p) for p in args.baseline_log],
		[Path(p) for p in args.mtp_log],
		run_id=str(args.run_id),
		model_id=str(args.model_id),
		runtime_id=str(args.runtime_id),
		quantization_id=str(args.quantization_id),
		prompt_id=str(args.prompt_id),
		prompt=str(args.prompt),
		prompt_hash=str(args.prompt_hash),
		n_predict=int(args.n_predict),
		stdout_suppressed=bool(args.stdout_suppressed),
		suppress_output_mode=str(args.suppress_output_mode),
		tail_acceptance_status=str(args.tail_acceptance_status),
		benchmark_matrix_status=str(args.benchmark_matrix_status),
	)
	errors = validate.validate_artifact(artifact)
	if errors:
		for error in errors:
			print(f"error: {error}", file=sys.stderr)
		return 2
	text = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
	if args.out_json:
		Path(args.out_json).write_text(text, encoding="utf-8")
	print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
