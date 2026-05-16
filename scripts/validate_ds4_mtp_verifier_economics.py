#!/usr/bin/env python3
"""Validate ds4-mtp-verifier-economics-v1 artifacts."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


FORMAT = "ds4-mtp-verifier-economics-v1"

REQUIRED_FIELDS = (
	"baseline_tps",
	"mtp_tps",
	"speedup_vs_baseline",
	"accepted_draft_tokens",
	"attempted_draft_tokens",
	"accept_rate",
	"emitted_tokens",
	"target_verifier_invocation_count",
	"target_positions_verified",
	"target_positions_per_invocation",
	"target_eval_ms",
	"target_eval_ms_per_invocation",
	"target_eval_ms_per_verified_position",
	"output_head_invocation_count",
	"output_head_rows",
	"full_vocab_logits_rows",
	"top1_only_rows",
	"draft_eval_ms",
	"snapshot_ms",
	"kv_commit_ms",
	"kv_restore_ms",
	"logits_readback_ms",
	"token_commit_ms",
	"slowest_component",
	"blocker_kind",
	"blocker_detail",
)

TARGET_SUFFIX_BLOCKER_FIELDS = (
	"target_suffix_verifier_implemented",
	"target_suffix_verifier_delegates_to_serial_decode",
	"staged_kv_ready",
	"true_suffix_blocker",
	"exact_next_code_change",
)


def _num(raw: Any) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def _require_nonnegative(errors: list[str], obj: dict[str, Any], field: str) -> None:
	val = _num(obj.get(field))
	if val is None or val < 0.0:
		errors.append(f"{field} must be a non-negative number")


def validate_report(obj: dict[str, Any]) -> dict[str, Any]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	for field in REQUIRED_FIELDS:
		if field not in obj:
			errors.append(f"missing required field: {field}")
	for field in REQUIRED_FIELDS:
		if field in {"slowest_component", "blocker_kind", "blocker_detail"}:
			continue
		if field in obj:
			_require_nonnegative(errors, obj, field)
	baseline = _num(obj.get("baseline_tps"))
	mtp = _num(obj.get("mtp_tps"))
	speedup = _num(obj.get("speedup_vs_baseline"))
	accepted = _num(obj.get("accepted_draft_tokens"))
	attempted = _num(obj.get("attempted_draft_tokens"))
	accept_rate = _num(obj.get("accept_rate"))
	invocations = _num(obj.get("target_verifier_invocation_count"))
	positions = _num(obj.get("target_positions_verified"))
	target_ms = _num(obj.get("target_eval_ms"))
	output_head_invocations = _num(obj.get("output_head_invocation_count"))
	output_head_rows = _num(obj.get("output_head_rows"))
	full_rows = _num(obj.get("full_vocab_logits_rows"))
	top1_rows = _num(obj.get("top1_only_rows"))
	if baseline is not None and mtp is not None and speedup is not None and baseline > 0.0:
		if abs(speedup - (mtp / baseline)) > 0.000001:
			errors.append("speedup_vs_baseline must equal mtp_tps / baseline_tps")
	if accept_rate is not None and accepted is not None and attempted is not None:
		if attempted <= 0.0:
			errors.append("accept_rate requires attempted_draft_tokens > 0")
		elif abs(accept_rate - (accepted / attempted)) > 0.000001:
			errors.append("accept_rate must equal accepted_draft_tokens / attempted_draft_tokens")
	if invocations is not None and positions is not None:
		per = _num(obj.get("target_positions_per_invocation"))
		if invocations <= 0.0:
			errors.append("target_verifier_invocation_count must be > 0")
		elif per is not None and abs(per - (positions / invocations)) > 0.000001:
			errors.append("target_positions_per_invocation must equal positions / invocations")
	if invocations is not None and target_ms is not None and invocations > 0.0:
		per = _num(obj.get("target_eval_ms_per_invocation"))
		if per is not None and abs(per - (target_ms / invocations)) > 0.000001:
			errors.append("target_eval_ms_per_invocation must equal target_eval_ms / invocations")
	if positions is not None and target_ms is not None and positions > 0.0:
		per = _num(obj.get("target_eval_ms_per_verified_position"))
		if per is not None and abs(per - (target_ms / positions)) > 0.000001:
			errors.append("target_eval_ms_per_verified_position must equal target_eval_ms / target_positions_verified")
	if output_head_invocations is not None and output_head_rows is not None and output_head_rows < output_head_invocations:
		errors.append("output_head_rows must be >= output_head_invocation_count")
	if full_rows is not None and top1_rows is not None and output_head_rows is not None:
		if abs((full_rows + top1_rows) - output_head_rows) > 0.000001:
			errors.append("full_vocab_logits_rows + top1_only_rows must equal output_head_rows")
	if baseline is not None and mtp is not None and mtp <= baseline:
		blocker = str(obj.get("blocker_kind", "") or "").strip()
		detail = str(obj.get("blocker_detail", "") or "").strip()
		if blocker == "" or blocker == "none" or detail == "":
			errors.append("MTP not faster than baseline requires blocker_kind and blocker_detail")
		if blocker in {"target_suffix_verifier_still_serial", "target_suffix_verifier_not_implemented"}:
			for field in TARGET_SUFFIX_BLOCKER_FIELDS:
				if field not in obj:
					errors.append(f"{blocker} requires {field}")
			if obj.get("target_suffix_verifier_implemented") is not True:
				errors.append(f"{blocker} requires target_suffix_verifier_implemented=true for the API prototype")
			if obj.get("target_suffix_verifier_delegates_to_serial_decode") is not True:
				errors.append(f"{blocker} requires target_suffix_verifier_delegates_to_serial_decode=true")
			if obj.get("staged_kv_ready") is not False:
				errors.append(f"{blocker} requires staged_kv_ready=false")
			for field in ("true_suffix_blocker", "exact_next_code_change"):
				if not isinstance(obj.get(field), str) or obj.get(field, "").strip() == "":
					errors.append(f"{blocker} requires non-empty {field}")
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
