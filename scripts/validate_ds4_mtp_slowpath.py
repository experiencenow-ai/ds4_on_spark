#!/usr/bin/env python3
"""Validate ds4-mtp-slowpath-v1 reports."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._lib.json_utils import number_or_none


REQUIRED_FIELDS = (
	"run_id",
	"model_id",
	"runtime_id",
	"prompt_hash",
	"mtp_draft",
	"mtp_margin",
	"accepted_tokens",
	"attempted_draft_tokens",
	"draft_tokens_accepted",
	"draft_tokens_attempted",
	"accept_rate",
	"baseline_generation_tps",
	"mtp_generation_tps",
	"speedup_vs_baseline",
	"target_next_mismatch_count",
	"target_next_mismatch_events",
	"slowest_component",
	"per_component_ms",
	"verifier_replay_ms",
	"verifier_ms",
	"draft_eval_ms",
	"target_eval_ms",
	"output_head_ms",
	"cache_sync_ms",
	"cuda_sync_ms",
	"logging_ms",
	"capture_ms",
	"logging_capture_ms",
	"token_commit_ms",
	"scheduler_overhead_ms",
	"target_eval_call_count",
	"draft_eval_call_count",
	"output_head_call_count",
	"verifier_replay_count",
	"cache_rewind_count",
	"cache_sync_count",
	"cuda_sync_count",
	"emitted_tokens",
	"target_eval_ms_per_emitted_token",
	"target_eval_ms_per_accepted_draft_token",
	"blocker_kind",
	"blocker_detail",
)

COMPONENT_FIELDS = (
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
			top = number_or_none(obj.get(field))
			nested = number_or_none(per_component.get(field))
			if top is not None and nested is not None and abs(top - nested) > 0.000001:
				errors.append(f"{field} must match per_component_ms.{field}")
	baseline = number_or_none(obj.get("baseline_generation_tps"))
	mtp = number_or_none(obj.get("mtp_generation_tps"))
	speedup = number_or_none(obj.get("speedup_vs_baseline"))
	accept_rate = number_or_none(obj.get("accept_rate"))
	accepted = number_or_none(obj.get("accepted_tokens"))
	attempted = number_or_none(obj.get("attempted_draft_tokens"))
	draft_accepted = number_or_none(obj.get("draft_tokens_accepted"))
	draft_attempted = number_or_none(obj.get("draft_tokens_attempted"))
	mismatch_count = number_or_none(obj.get("target_next_mismatch_count"))
	mismatch_events = number_or_none(obj.get("target_next_mismatch_events"))
	if speedup is not None and baseline is None:
		errors.append("speedup claim requires baseline_generation_tps")
	if accept_rate is not None:
		if draft_accepted is None or draft_attempted is None:
			errors.append("accept_rate requires draft_tokens_accepted and draft_tokens_attempted")
		elif draft_attempted <= 0.0:
			errors.append("accept_rate requires draft_tokens_attempted > 0")
	if speedup is not None and speedup > 1.0 and baseline is not None and mtp is not None and mtp <= baseline:
		errors.append("speedup_vs_baseline > 1 is invalid when mtp_generation_tps <= baseline_generation_tps")
	if "target_next_mismatch_count" not in obj or obj.get("target_next_mismatch_count") is None:
		errors.append("missing target_next_mismatch_count")
	if "target_next_mismatch_events" not in obj or obj.get("target_next_mismatch_events") is None:
		errors.append("missing target_next_mismatch_events")
	if accepted is not None and draft_accepted is not None and abs(accepted - draft_accepted) > 0.000001:
		errors.append("draft_tokens_accepted must match accepted_tokens")
	if attempted is not None and draft_attempted is not None and abs(attempted - draft_attempted) > 0.000001:
		errors.append("draft_tokens_attempted must match attempted_draft_tokens")
	if mismatch_count is not None and mismatch_events is not None and abs(mismatch_count - mismatch_events) > 0.000001:
		errors.append("target_next_mismatch_events must match target_next_mismatch_count")
	logging_capture = number_or_none(obj.get("logging_capture_ms"))
	logging_ms = number_or_none(obj.get("logging_ms"))
	capture_ms = number_or_none(obj.get("capture_ms"))
	if logging_capture is not None and logging_ms is not None and capture_ms is not None:
		if abs(logging_capture - (logging_ms + capture_ms)) > 0.000001:
			errors.append("logging_capture_ms must equal logging_ms + capture_ms")
	if baseline is not None and mtp is not None and mtp < baseline:
		blocker = str(obj.get("blocker_kind", "") or "").strip()
		if blocker == "" or blocker == "none":
			errors.append("MTP slower than baseline requires blocker_kind")
	emitted = number_or_none(obj.get("emitted_tokens"))
	target_eval = number_or_none(obj.get("target_eval_ms"))
	target_per_emitted = number_or_none(obj.get("target_eval_ms_per_emitted_token"))
	target_per_accepted = number_or_none(obj.get("target_eval_ms_per_accepted_draft_token"))
	if emitted is not None and emitted > 0.0 and target_eval is not None and target_per_emitted is not None:
		if abs(target_per_emitted - (target_eval / emitted)) > 0.000001:
			errors.append("target_eval_ms_per_emitted_token must equal target_eval_ms / emitted_tokens")
	if draft_accepted is not None and draft_accepted > 0.0 and target_eval is not None and target_per_accepted is not None:
		if abs(target_per_accepted - (target_eval / draft_accepted)) > 0.000001:
			errors.append("target_eval_ms_per_accepted_draft_token must equal target_eval_ms / draft_tokens_accepted")
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
