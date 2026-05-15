#!/usr/bin/env python3
"""Validate ds4-mtp-slowpath-v1 reports."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


REQUIRED_FIELDS = (
	"run_id",
	"model_id",
	"runtime_id",
	"prompt_hash",
	"mtp_draft",
	"mtp_margin",
	"accepted_tokens",
	"attempted_draft_tokens",
	"accept_rate",
	"baseline_generation_tps",
	"mtp_generation_tps",
	"speedup_vs_baseline",
	"target_next_mismatch_count",
	"slowest_component",
	"per_component_ms",
	"verifier_replay_ms",
	"draft_eval_ms",
	"target_eval_ms",
	"cache_sync_ms",
	"cuda_sync_ms",
	"logging_ms",
	"capture_ms",
	"token_commit_ms",
	"blocker_kind",
	"blocker_detail",
)

COMPONENT_FIELDS = (
	"verifier_replay_ms",
	"draft_eval_ms",
	"target_eval_ms",
	"cache_sync_ms",
	"cuda_sync_ms",
	"logging_ms",
	"capture_ms",
	"token_commit_ms",
)


def _num_or_none(raw: Any) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def validate_report(obj: dict[str, Any]) -> dict[str, Any]:
	errors: list[str] = []
	if obj.get("format") != "ds4-mtp-slowpath-v1":
		errors.append("format must be ds4-mtp-slowpath-v1")
	for field in REQUIRED_FIELDS:
		if field not in obj:
			errors.append(f"missing required field: {field}")
	per_component = obj.get("per_component_ms")
	if not isinstance(per_component, dict):
		errors.append("per_component_ms must be an object")
		per_component = {}
	for field in COMPONENT_FIELDS:
		if field not in per_component:
			errors.append(f"per_component_ms missing component: {field}")
		if field in obj and field in per_component:
			top = _num_or_none(obj.get(field))
			nested = _num_or_none(per_component.get(field))
			if top is not None and nested is not None and abs(top - nested) > 0.000001:
				errors.append(f"{field} must match per_component_ms.{field}")
	baseline = _num_or_none(obj.get("baseline_generation_tps"))
	mtp = _num_or_none(obj.get("mtp_generation_tps"))
	speedup = _num_or_none(obj.get("speedup_vs_baseline"))
	accept_rate = _num_or_none(obj.get("accept_rate"))
	accepted = _num_or_none(obj.get("accepted_tokens"))
	attempted = _num_or_none(obj.get("attempted_draft_tokens"))
	if speedup is not None and baseline is None:
		errors.append("speedup claim requires baseline_generation_tps")
	if accept_rate is not None:
		if accepted is None or attempted is None:
			errors.append("accept_rate requires accepted_tokens and attempted_draft_tokens")
		elif attempted <= 0.0:
			errors.append("accept_rate requires attempted_draft_tokens > 0")
	if speedup is not None and speedup > 1.0 and baseline is not None and mtp is not None and mtp <= baseline:
		errors.append("speedup_vs_baseline > 1 is invalid when mtp_generation_tps <= baseline_generation_tps")
	if "target_next_mismatch_count" not in obj or obj.get("target_next_mismatch_count") is None:
		errors.append("missing target_next_mismatch_count")
	if baseline is not None and mtp is not None and mtp < baseline:
		blocker = str(obj.get("blocker_kind", "") or "").strip()
		if blocker == "" or blocker == "none":
			errors.append("MTP slower than baseline requires blocker_kind")
	return {
		"ok": len(errors) == 0,
		"errors": errors,
	}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("path", help="Report JSON path, or '-' for stdin.")
	ap.add_argument("--json", action="store_true", help="Print validation JSON (default).")
	args = ap.parse_args(argv)
	if str(args.path) == "-":
		obj = json.load(sys.stdin)
	else:
		obj = json.loads(Path(str(args.path)).read_text(encoding="utf-8"))
	res = validate_report(obj)
	print(json.dumps(res, indent=2, sort_keys=True))
	return 0 if bool(res.get("ok", False)) else 1


if __name__ == "__main__":
	raise SystemExit(main())
