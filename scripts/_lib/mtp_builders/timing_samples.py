#!/usr/bin/env python3
"""Build ds4-mtp-timing-samples-v1 from repeated DS4 MTP sample JSON files."""

from __future__ import annotations

import json
import statistics
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


FORMAT = "ds4-mtp-timing-samples-v1"


def _num(raw: Any) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def _int(raw: Any) -> Optional[int]:
	val = _num(raw)
	if val is None:
		return None
	if float(int(val)) != val:
		return None
	return int(val)


def _bench_value(obj: dict[str, Any], key: str) -> Any:
	for ev in reversed((((obj.get("benchmark") or {}).get("events")) or [])):
		if key in ev:
			return ev.get(key)
	return None


def _diag_draft_counts(diag: Any) -> tuple[Optional[int], Optional[int]]:
	if not isinstance(diag, dict):
		return None, None
	attempts = _int(diag.get("suffix2_attempts"))
	tail_attempts = _int(diag.get("suffix2_tail_attempts")) or 0
	full_accepts = _int(diag.get("suffix2_full_accepts")) or 0
	partial_accepts = _int(diag.get("suffix2_partial_accepts")) or 0
	tail_accepts = _int(diag.get("suffix2_tail_accepts")) or 0
	if attempts is None:
		return None, None
	if tail_attempts > attempts:
		return None, None
	non_tail_attempts = attempts - tail_attempts
	attempted = (2 * non_tail_attempts) + tail_attempts
	accepted = (2 * full_accepts) + partial_accepts + tail_accepts
	return accepted, attempted


def _sample_from_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	speed = obj.get("speed") or {}
	totals = obj.get("totals") or {}
	mismatches = obj.get("mismatches") or {}
	timing = obj.get("timing") or {}
	sample_diag = obj.get("sample_diag")
	generation_tps = speed.get("generation_tps")
	if generation_tps is None:
		generation_tps = obj.get("mtp_tps") or obj.get("mtp_generation_tps")
	accepted_draft_tokens = _int(totals.get("draft_tokens_accepted_est") if totals else obj.get("accepted_draft_tokens"))
	attempted_draft_tokens = _int(totals.get("draft_tokens_attempted_est") if totals else obj.get("attempted_draft_tokens"))
	diag_accepted, diag_attempted = _diag_draft_counts(sample_diag)
	if (attempted_draft_tokens is None or attempted_draft_tokens == 0) and diag_attempted is not None and diag_attempted > 0:
		accepted_draft_tokens = diag_accepted
		attempted_draft_tokens = diag_attempted
	accept_rate = _num(totals.get("draft_accept_rate_est") if totals else obj.get("accept_rate"))
	if (accept_rate is None or (attempted_draft_tokens is not None and attempted_draft_tokens > 0 and accept_rate == 0.0)) and attempted_draft_tokens is not None and attempted_draft_tokens > 0 and accepted_draft_tokens is not None:
		accept_rate = accepted_draft_tokens / attempted_draft_tokens
	return {
		"path": str(path),
		"generation_tps": _num(generation_tps),
		"prefill_tps": _num(speed.get("prefill_tps")),
		"external_wall_s": _num(_bench_value(obj, "external_wall_s")),
		"phase": _bench_value(obj, "phase"),
		"command_sha256": _bench_value(obj, "command_sha256"),
		"perf_env_sha256": _bench_value(obj, "perf_env_sha256"),
		"perf_env_keys": _bench_value(obj, "perf_env_keys"),
		"prompt_sha256": _bench_value(obj, "prompt_sha256") or obj.get("prompt_hash"),
		"n_predict": _int(_bench_value(obj, "n_predict")),
		"mtp_draft": _int(_bench_value(obj, "mtp_draft") or obj.get("mtp_draft")),
		"ctx": _int(_bench_value(obj, "ctx")),
		"seed": _int(_bench_value(obj, "seed")),
		"spec_disabled": _int(_bench_value(obj, "spec_disabled")),
		"exit_code": _int(_bench_value(obj, "exit_code")),
		"accept_rate": accept_rate,
		"accepted_draft_tokens": accepted_draft_tokens,
		"attempted_draft_tokens": attempted_draft_tokens,
		"target_next_mismatch_events": _int(mismatches.get("target_next_mismatch_events") if mismatches else obj.get("target_next_mismatch_events")),
		"timing_event_count": _int((timing or {}).get("events")),
		"sample_diag": sample_diag,
	}


def _unique_nonempty(samples: list[dict[str, Any]], key: str) -> list[Any]:
	vals = []
	for sample in samples:
		val = sample.get(key)
		if val is not None and val != "" and val not in vals:
			vals.append(val)
	return vals


def _percentile(vals: list[float], p: float) -> Optional[float]:
	if not vals:
		return None
	if len(vals) == 1:
		return vals[0]
	ordered = sorted(vals)
	pos = (len(ordered) - 1) * p
	lo = int(pos)
	hi = min(lo + 1, len(ordered) - 1)
	frac = pos - lo
	return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _stats(vals: list[float]) -> dict[str, Any]:
	if not vals:
		return {
			"count": 0,
			"min": None,
			"max": None,
			"mean": None,
			"median": None,
			"stdev": None,
			"cv": None,
			"p10": None,
			"p90": None,
			"iqr": None,
		}
	mean = statistics.mean(vals)
	stdev = statistics.stdev(vals) if len(vals) > 1 else 0.0
	q1 = _percentile(vals, 0.25)
	q3 = _percentile(vals, 0.75)
	return {
		"count": len(vals),
		"min": min(vals),
		"max": max(vals),
		"mean": mean,
		"median": statistics.median(vals),
		"stdev": stdev,
		"cv": (stdev / mean) if mean > 0.0 else None,
		"p10": _percentile(vals, 0.10),
		"p90": _percentile(vals, 0.90),
		"iqr": (q3 - q1) if q1 is not None and q3 is not None else None,
	}


def _consistent(samples: list[dict[str, Any]], key: str) -> bool:
	return len(_unique_nonempty(samples, key)) <= 1


def build_report(
	sample_paths: list[Path],
	*,
	run_id: str,
	label: str,
	min_sample_count: int,
	baseline_tps: Optional[float],
) -> dict[str, Any]:
	if min_sample_count <= 0:
		raise ValueError("min_sample_count must be positive")
	samples = [_sample_from_json(path) for path in sample_paths]
	valid_tps = [
		float(sample["generation_tps"])
		for sample in samples
		if _num(sample.get("generation_tps")) is not None and float(sample["generation_tps"]) > 0.0
	]
	status = "passed"
	blockers: list[str] = []
	if len(valid_tps) < min_sample_count:
		status = "insufficient_samples"
		blockers.append(f"requires at least {min_sample_count} valid timing samples")
	for key in ("prompt_sha256", "command_sha256", "perf_env_sha256", "n_predict", "mtp_draft", "ctx", "seed", "spec_disabled"):
		if not _consistent(samples, key):
			status = "blocked"
			blockers.append(f"sample mismatch for {key}")
	bad_exit = [sample for sample in samples if _int(sample.get("exit_code")) not in (None, 0)]
	if bad_exit:
		status = "blocked"
		blockers.append("one or more samples had non-zero exit_code")
	stats = _stats(valid_tps)
	median = _num(stats.get("median"))
	return {
		"format": FORMAT,
		"run_id": run_id,
		"label": label,
		"sample_status": status,
		"blocker_detail": "; ".join(blockers),
		"sample_count": len(valid_tps),
		"input_file_count": len(sample_paths),
		"min_sample_count": min_sample_count,
		"generation_tps_samples": valid_tps,
		"generation_tps_min": stats["min"],
		"generation_tps_max": stats["max"],
		"generation_tps_mean": stats["mean"],
		"generation_tps_median": stats["median"],
		"generation_tps_stdev": stats["stdev"],
		"generation_tps_cv": stats["cv"],
		"generation_tps_p10": stats["p10"],
		"generation_tps_p90": stats["p90"],
		"generation_tps_iqr": stats["iqr"],
		"baseline_tps": baseline_tps,
		"speedup_vs_baseline_median": (median / baseline_tps) if median is not None and baseline_tps and baseline_tps > 0.0 else None,
		"prompt_sha256": (_unique_nonempty(samples, "prompt_sha256") or [None])[0],
		"command_sha256": (_unique_nonempty(samples, "command_sha256") or [None])[0],
		"perf_env_sha256": (_unique_nonempty(samples, "perf_env_sha256") or [None])[0],
		"perf_env_keys": (_unique_nonempty(samples, "perf_env_keys") or [None])[0],
		"n_predict": (_unique_nonempty(samples, "n_predict") or [None])[0],
		"mtp_draft": (_unique_nonempty(samples, "mtp_draft") or [None])[0],
		"ctx": (_unique_nonempty(samples, "ctx") or [None])[0],
		"seed": (_unique_nonempty(samples, "seed") or [None])[0],
		"spec_disabled": (_unique_nonempty(samples, "spec_disabled") or [None])[0],
		"sample_records": samples,
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--sample-json", action="append", default=[])
	ap.add_argument("--sample-dir", action="append", default=[])
	ap.add_argument("--run-id", required=True)
	ap.add_argument("--label", default="")
	ap.add_argument("--min-sample-count", type=int, default=10)
	ap.add_argument("--baseline-tps", type=float, default=None)
	ap.add_argument("--out-json", default="")
	args = ap.parse_args(argv)
	paths = [Path(p) for p in args.sample_json]
	for raw in args.sample_dir:
		paths.extend(sorted(Path(raw).glob("*/acceptance_summary.json")))
	if not paths:
		raise SystemExit("at least one --sample-json or --sample-dir is required")
	report = build_report(
		paths,
		run_id=str(args.run_id),
		label=str(args.label),
		min_sample_count=int(args.min_sample_count),
		baseline_tps=args.baseline_tps,
	)
	text = json.dumps(report, indent=2, sort_keys=True) + "\n"
	if str(args.out_json).strip() != "":
		Path(str(args.out_json)).write_text(text, encoding="utf-8")
	print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
