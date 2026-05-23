#!/usr/bin/env python3
"""Validate ds4-mtp-benchmark-integrity-v1 artifacts."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._lib.json_utils import number_or_none


FORMAT = "ds4-mtp-benchmark-integrity-v1"

REQUIRED_FIELDS = (
	"benchmark_status",
	"same_cli_path",
	"same_perf_env",
	"baseline_spec_disabled",
	"mtp_spec_enabled",
	"baseline_perf_env_sha256",
	"mtp_perf_env_sha256",
	"baseline_reported_generation_tps",
	"mtp_reported_generation_tps",
	"speedup_vs_session_baseline",
	"baseline_external_process_wall_s",
	"mtp_external_process_wall_s",
	"baseline_exit_code",
	"mtp_exit_code",
)


def validate_report(obj: dict[str, Any]) -> dict[str, Any]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	for field in REQUIRED_FIELDS:
		if field not in obj:
			errors.append(f"missing required field: {field}")
	for field in (
		"baseline_reported_generation_tps",
		"mtp_reported_generation_tps",
		"speedup_vs_session_baseline",
		"baseline_external_process_wall_s",
		"mtp_external_process_wall_s",
	):
		if field in obj:
			val = number_or_none(obj.get(field))
			if val is None or val < 0.0:
				errors.append(f"{field} must be a non-negative number")
	base = number_or_none(obj.get("baseline_reported_generation_tps"))
	mtp = number_or_none(obj.get("mtp_reported_generation_tps"))
	speedup = number_or_none(obj.get("speedup_vs_session_baseline"))
	if base is not None and mtp is not None and speedup is not None and base > 0.0:
		if abs(speedup - (mtp / base)) > 0.000001:
			errors.append("speedup_vs_session_baseline must equal mtp_reported_generation_tps / baseline_reported_generation_tps")
	status = str(obj.get("benchmark_status", "") or "")
	if status not in {"comparable", "blocked"}:
		errors.append("benchmark_status must be comparable or blocked")
	if status == "comparable":
		if obj.get("same_cli_path") is not True:
			errors.append("comparable benchmark requires same_cli_path=true")
		if obj.get("same_perf_env") is not True:
			errors.append("comparable benchmark requires same_perf_env=true")
		if obj.get("baseline_spec_disabled") is not True:
			errors.append("comparable benchmark requires baseline_spec_disabled=true")
		if obj.get("mtp_spec_enabled") is not True:
			errors.append("comparable benchmark requires mtp_spec_enabled=true")
		if number_or_none(obj.get("baseline_exit_code")) != 0.0 or number_or_none(obj.get("mtp_exit_code")) != 0.0:
			errors.append("comparable benchmark requires zero exit codes")
	else:
		if str(obj.get("blocker_detail", "") or "").strip() == "":
			errors.append("blocked benchmark requires blocker_detail")
	prior = number_or_none(obj.get("prior_argmax_baseline_tps"))
	prior_speedup = number_or_none(obj.get("speedup_vs_prior_argmax_baseline"))
	if prior is not None and prior_speedup is not None and mtp is not None and prior > 0.0:
		if abs(prior_speedup - (mtp / prior)) > 0.000001:
			errors.append("speedup_vs_prior_argmax_baseline must equal mtp_reported_generation_tps / prior_argmax_baseline_tps")
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
