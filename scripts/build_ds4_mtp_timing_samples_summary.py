#!/usr/bin/env python3
"""Build a median comparison summary from baseline and MTP timing samples."""

from __future__ import annotations

import json
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


FORMAT = "ds4-mtp-timing-samples-summary-v1"


def _num(raw: Any) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def build_summary(
	baseline_path: Path,
	mtp_path: Path,
	*,
	max_cv_for_direction: float,
) -> dict[str, Any]:
	baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
	mtp = json.loads(mtp_path.read_text(encoding="utf-8"))
	baseline_median = _num(baseline.get("generation_tps_median"))
	mtp_median = _num(mtp.get("generation_tps_median"))
	baseline_cv = _num(baseline.get("generation_tps_cv"))
	mtp_cv = _num(mtp.get("generation_tps_cv"))
	speedup = (mtp_median / baseline_median) if baseline_median is not None and baseline_median > 0.0 and mtp_median is not None else None
	baseline_passed = baseline.get("sample_status") == "passed"
	mtp_passed = mtp.get("sample_status") == "passed"
	baseline_stable = baseline_cv is not None and baseline_cv <= max_cv_for_direction
	mtp_stable = mtp_cv is not None and mtp_cv <= max_cv_for_direction
	status = "passed"
	blockers: list[str] = []
	if not baseline_passed or not mtp_passed:
		status = "blocked"
		blockers.append("baseline and MTP timing sample reports must both pass")
	elif not baseline_stable or not mtp_stable:
		status = "unstable"
		if not baseline_stable:
			blockers.append("baseline generation_tps_cv exceeds stability threshold")
		if not mtp_stable:
			blockers.append("MTP generation_tps_cv exceeds stability threshold")
	return {
		"format": FORMAT,
		"baseline_report": str(baseline_path),
		"mtp_report": str(mtp_path),
		"baseline_sample_status": baseline.get("sample_status"),
		"mtp_sample_status": mtp.get("sample_status"),
		"sample_count": mtp.get("sample_count"),
		"max_cv_for_direction": max_cv_for_direction,
		"baseline_generation_tps_median": baseline_median,
		"baseline_generation_tps_mean": baseline.get("generation_tps_mean"),
		"baseline_generation_tps_stdev": baseline.get("generation_tps_stdev"),
		"baseline_generation_tps_cv": baseline_cv,
		"baseline_timing_stable": baseline_stable,
		"mtp_generation_tps_median": mtp_median,
		"mtp_generation_tps_mean": mtp.get("generation_tps_mean"),
		"mtp_generation_tps_stdev": mtp.get("generation_tps_stdev"),
		"mtp_generation_tps_cv": mtp_cv,
		"mtp_timing_stable": mtp_stable,
		"speedup_vs_baseline_median": speedup,
		"decision_status": status,
		"blocker_detail": "; ".join(blockers),
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("--baseline-report", required=True)
	ap.add_argument("--mtp-report", required=True)
	ap.add_argument("--max-cv-for-direction", type=float, default=0.15)
	ap.add_argument("--out-json", default="")
	args = ap.parse_args(argv)
	if args.max_cv_for_direction <= 0.0:
		raise SystemExit("--max-cv-for-direction must be positive")
	report = build_summary(
		Path(str(args.baseline_report)),
		Path(str(args.mtp_report)),
		max_cv_for_direction=float(args.max_cv_for_direction),
	)
	text = json.dumps(report, indent=2, sort_keys=True) + "\n"
	if str(args.out_json).strip() != "":
		Path(str(args.out_json)).write_text(text, encoding="utf-8")
	print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
