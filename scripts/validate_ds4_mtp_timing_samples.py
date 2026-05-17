#!/usr/bin/env python3
"""Validate ds4-mtp-timing-samples-v1 repeated timing reports."""

from __future__ import annotations

import json
import math
import statistics
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


FORMAT = "ds4-mtp-timing-samples-v1"

REQUIRED_FIELDS = (
	"run_id",
	"label",
	"sample_status",
	"blocker_detail",
	"sample_count",
	"input_file_count",
	"min_sample_count",
	"generation_tps_samples",
	"generation_tps_min",
	"generation_tps_max",
	"generation_tps_mean",
	"generation_tps_median",
	"generation_tps_stdev",
	"generation_tps_cv",
	"generation_tps_p10",
	"generation_tps_p90",
	"generation_tps_iqr",
	"baseline_tps",
	"speedup_vs_baseline_median",
	"prompt_sha256",
	"command_sha256",
	"perf_env_sha256",
	"n_predict",
	"mtp_draft",
	"ctx",
	"seed",
	"spec_disabled",
	"sample_records",
)

STATUS_VALUES = {"passed", "insufficient_samples", "blocked"}


def _num(raw: Any) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		val = float(raw)
	else:
		try:
			val = float(str(raw).strip())
		except (TypeError, ValueError):
			return None
	if math.isnan(val) or math.isinf(val):
		return None
	return val


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


def _close(a: Optional[float], b: Optional[float], tol: float = 0.000001) -> bool:
	if a is None or b is None:
		return a is None and b is None
	return abs(a - b) <= tol


def _unique_nonempty(records: list[dict[str, Any]], key: str) -> list[Any]:
	vals = []
	for record in records:
		val = record.get(key)
		if val is not None and val != "" and val not in vals:
			vals.append(val)
	return vals


def validate_report(obj: dict[str, Any]) -> dict[str, Any]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	for field in REQUIRED_FIELDS:
		if field not in obj:
			errors.append(f"missing required field: {field}")
	status = str(obj.get("sample_status", "") or "")
	if status not in STATUS_VALUES:
		errors.append("sample_status must be passed, insufficient_samples, or blocked")
	blocker_detail = str(obj.get("blocker_detail", "") or "").strip()
	if status in {"insufficient_samples", "blocked"} and blocker_detail == "":
		errors.append("non-passed sample_status requires blocker_detail")
	if status == "passed" and blocker_detail != "":
		errors.append("passed sample_status must not set blocker_detail")
	min_count = _num(obj.get("min_sample_count"))
	sample_count = _num(obj.get("sample_count"))
	input_count = _num(obj.get("input_file_count"))
	if min_count is None or min_count < 10.0 or float(int(min_count)) != min_count:
		errors.append("min_sample_count must be an integer >= 10")
	if sample_count is None or sample_count < 0.0 or float(int(sample_count)) != sample_count:
		errors.append("sample_count must be a non-negative integer")
	if input_count is None or input_count < 0.0 or float(int(input_count)) != input_count:
		errors.append("input_file_count must be a non-negative integer")
	samples_raw = obj.get("generation_tps_samples")
	if not isinstance(samples_raw, list):
		errors.append("generation_tps_samples must be an array")
		samples: list[float] = []
	else:
		samples = []
		for idx, raw in enumerate(samples_raw):
			val = _num(raw)
			if val is None or val <= 0.0:
				errors.append(f"generation_tps_samples[{idx}] must be positive")
			else:
				samples.append(val)
	if sample_count is not None and int(sample_count) != len(samples):
		errors.append("sample_count must equal valid generation_tps_samples length")
	if status == "passed" and min_count is not None and sample_count is not None and sample_count < min_count:
		errors.append("passed timing report requires sample_count >= min_sample_count")
	if status == "insufficient_samples" and min_count is not None and sample_count is not None and sample_count >= min_count:
		errors.append("insufficient_samples requires sample_count < min_sample_count")
	if samples:
		stats = {
			"generation_tps_min": min(samples),
			"generation_tps_max": max(samples),
			"generation_tps_mean": statistics.mean(samples),
			"generation_tps_median": statistics.median(samples),
			"generation_tps_stdev": statistics.stdev(samples) if len(samples) > 1 else 0.0,
			"generation_tps_p10": _percentile(samples, 0.10),
			"generation_tps_p90": _percentile(samples, 0.90),
		}
		q1 = _percentile(samples, 0.25)
		q3 = _percentile(samples, 0.75)
		stats["generation_tps_iqr"] = (q3 - q1) if q1 is not None and q3 is not None else None
		mean = stats["generation_tps_mean"]
		stats["generation_tps_cv"] = (stats["generation_tps_stdev"] / mean) if mean > 0.0 else None
		for field, expected in stats.items():
			if not _close(_num(obj.get(field)), expected):
				errors.append(f"{field} must match generation_tps_samples")
	baseline = _num(obj.get("baseline_tps"))
	median = _num(obj.get("generation_tps_median"))
	speedup = _num(obj.get("speedup_vs_baseline_median"))
	if baseline is not None and baseline <= 0.0:
		errors.append("baseline_tps must be positive when provided")
	if baseline is not None and median is not None and speedup is not None:
		if not _close(speedup, median / baseline):
			errors.append("speedup_vs_baseline_median must equal generation_tps_median / baseline_tps")
		if speedup > 1.0 and median <= baseline:
			errors.append("speedup_vs_baseline_median > 1 is invalid when generation_tps_median <= baseline_tps")
	if baseline is not None and speedup is None:
		errors.append("baseline_tps requires speedup_vs_baseline_median")
	records_raw = obj.get("sample_records")
	if not isinstance(records_raw, list):
		errors.append("sample_records must be an array")
		records: list[dict[str, Any]] = []
	else:
		records = []
		for idx, record in enumerate(records_raw):
			if not isinstance(record, dict):
				errors.append(f"sample_records[{idx}] must be an object")
			else:
				records.append(record)
	if input_count is not None and int(input_count) != len(records):
		errors.append("input_file_count must equal sample_records length")
	for key in ("prompt_sha256", "command_sha256", "perf_env_sha256", "n_predict", "mtp_draft", "ctx", "seed", "spec_disabled"):
		if len(_unique_nonempty(records, key)) > 1 and status != "blocked":
			errors.append(f"sample_records mismatch for {key} requires sample_status=blocked")
	bad_exit = [record for record in records if _num(record.get("exit_code")) not in (None, 0.0)]
	if bad_exit and status != "blocked":
		errors.append("non-zero sample exit_code requires sample_status=blocked")
	return {"ok": len(errors) == 0, "errors": errors}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("path")
	args = ap.parse_args(argv)
	if str(args.path) == "-":
		obj = json.load(sys.stdin)
	else:
		obj = json.loads(Path(str(args.path)).read_text(encoding="utf-8"))
	res = validate_report(obj)
	print(json.dumps(res, indent=2, sort_keys=True))
	return 0 if bool(res.get("ok")) else 1


if __name__ == "__main__":
	raise SystemExit(main())
