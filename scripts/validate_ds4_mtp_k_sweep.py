#!/usr/bin/env python3
"""Validate ds4-mtp-k-sweep-v1 artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any, Optional


FORMAT = "ds4-mtp-k-sweep-v1"

REQUIRED_TOP = (
	"run_id",
	"model_id",
	"runtime_id",
	"k_power_of_two_required",
	"k_values_tested_or_classified",
	"runtime_supported_k",
	"idle_extra_rows_swept",
	"accept_prob_used_for_projection",
	"reference_measurements",
	"k_results",
	"best_supported_k_by_idle_rows",
	"best_projected_k_by_idle_rows",
	"integration_rule",
	"blocker_kind",
	"blocker_detail",
	"artifact_sha256",
)

REQUIRED_ROW = (
	"k",
	"k_power_of_two",
	"runtime_supported",
	"measurement_status",
	"expected_accept_prob_per_draft_token",
	"expected_emitted_tokens_per_group",
	"total_target_verifier_rows_per_group",
	"extra_idle_rows_required_per_promoted_sequence",
	"expected_target_rows_per_output_token",
	"expected_draft_calls_per_output_token",
	"expected_bonus_tokens_per_extra_idle_row",
	"fits_idle_extra_rows",
	"blocker_kind",
	"blocker_detail",
)

MEASURED_ROW = (
	"baseline_tps",
	"mtp_tps",
	"speedup_vs_baseline",
	"accept_rate",
	"accepted_draft_tokens",
	"attempted_draft_tokens",
	"emitted_tokens",
	"target_verifier_invocation_count",
	"target_positions_verified",
	"target_positions_per_invocation",
	"output_head_invocation_count",
	"full_vocab_logits_rows",
	"top1_only_rows",
	"slowest_component",
)


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	tmp.pop("artifact_hash", None)
	return "sha256:" + hashlib.sha256(canonical_bytes(tmp)).hexdigest()


def _num(raw: Any) -> Optional[float]:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def _int_list(raw: Any) -> Optional[list[int]]:
	if not isinstance(raw, list):
		return None
	out: list[int] = []
	for item in raw:
		if not isinstance(item, int) or item < 0:
			return None
		out.append(item)
	return out


def _close(a: float, b: float, tol: float = 0.000001) -> bool:
	return abs(a - b) <= tol


def is_power_of_two(value: int) -> bool:
	return value > 0 and (value & (value - 1)) == 0


def expected_emitted_tokens(k: int, accept_prob: float) -> float:
	total = 0.0
	for i in range(k + 1):
		total += accept_prob ** i
	return total


def validate_measured(errors: list[str], row: dict[str, Any], prefix: str) -> None:
	for field in MEASURED_ROW:
		if field not in row:
			errors.append(f"{prefix} missing measured field: {field}")
	baseline = _num(row.get("baseline_tps"))
	mtp = _num(row.get("mtp_tps"))
	speedup = _num(row.get("speedup_vs_baseline"))
	if baseline is not None and mtp is not None and speedup is not None and baseline > 0.0:
		if not _close(speedup, mtp / baseline):
			errors.append(f"{prefix} speedup_vs_baseline must equal mtp_tps / baseline_tps")
	accepted = _num(row.get("accepted_draft_tokens"))
	attempted = _num(row.get("attempted_draft_tokens"))
	accept_rate = _num(row.get("accept_rate"))
	if accepted is not None and attempted is not None and accept_rate is not None:
		if attempted <= 0.0:
			errors.append(f"{prefix} accept_rate requires attempted_draft_tokens > 0")
		elif not _close(accept_rate, accepted / attempted):
			errors.append(f"{prefix} accept_rate must equal accepted_draft_tokens / attempted_draft_tokens")
	invocations = _num(row.get("target_verifier_invocation_count"))
	positions = _num(row.get("target_positions_verified"))
	per = _num(row.get("target_positions_per_invocation"))
	if invocations is not None and positions is not None and per is not None and invocations > 0.0:
		if not _close(per, positions / invocations):
			errors.append(f"{prefix} target_positions_per_invocation must equal positions / invocations")
	if "k" in row and per is not None:
		k = int(row["k"])
		if not _close(per, float(k + 1)):
			errors.append(f"{prefix} inferred K must equal target_positions_per_invocation - 1")


def validate_row(errors: list[str], row: Any, idle_slots: list[int], supported_k: set[int], index: int) -> None:
	prefix = f"k_results[{index}]"
	if not isinstance(row, dict):
		errors.append(f"{prefix} must be an object")
		return
	for field in REQUIRED_ROW:
		if field not in row:
			errors.append(f"{prefix} missing required field: {field}")
	k_raw = row.get("k")
	if not isinstance(k_raw, int) or k_raw <= 0:
		errors.append(f"{prefix} k must be a positive integer")
		return
	k = int(k_raw)
	if row.get("k_power_of_two") is not is_power_of_two(k):
		errors.append(f"{prefix} k_power_of_two is wrong")
	if row.get("runtime_supported") is not (k in supported_k):
		errors.append(f"{prefix} runtime_supported must match runtime_supported_k")
	accept_prob = _num(row.get("expected_accept_prob_per_draft_token"))
	if accept_prob is None or accept_prob < 0.0 or accept_prob > 1.0:
		errors.append(f"{prefix} expected_accept_prob_per_draft_token must be in [0,1]")
		return
	expected = expected_emitted_tokens(k, accept_prob)
	if not _close(float(row.get("expected_emitted_tokens_per_group", -1.0)), expected):
		errors.append(f"{prefix} expected_emitted_tokens_per_group formula mismatch")
	if row.get("total_target_verifier_rows_per_group") != k + 1:
		errors.append(f"{prefix} total_target_verifier_rows_per_group must equal K + 1")
	if row.get("extra_idle_rows_required_per_promoted_sequence") != k:
		errors.append(f"{prefix} extra_idle_rows_required_per_promoted_sequence must equal K")
	target_rows = _num(row.get("expected_target_rows_per_output_token"))
	if target_rows is not None and not _close(target_rows, (k + 1) / expected):
		errors.append(f"{prefix} expected_target_rows_per_output_token formula mismatch")
	draft_calls = _num(row.get("expected_draft_calls_per_output_token"))
	if draft_calls is not None and not _close(draft_calls, k / expected):
		errors.append(f"{prefix} expected_draft_calls_per_output_token formula mismatch")
	bonus = _num(row.get("expected_bonus_tokens_per_extra_idle_row"))
	if bonus is not None and not _close(bonus, (expected - 1.0) / k):
		errors.append(f"{prefix} expected_bonus_tokens_per_extra_idle_row formula mismatch")
	fits = row.get("fits_idle_extra_rows")
	if not isinstance(fits, dict):
		errors.append(f"{prefix} fits_idle_extra_rows must be an object")
	else:
		for slots in idle_slots:
			if fits.get(str(slots)) is not (slots >= k):
				errors.append(f"{prefix} fits_idle_extra_rows[{slots}] must equal idle_extra_rows >= K")
	status = str(row.get("measurement_status", "") or "")
	if status not in {"measured", "supported_unmeasured", "projected_unsupported_runtime"}:
		errors.append(f"{prefix} invalid measurement_status")
	if status == "measured":
		validate_measured(errors, row, prefix)
	elif k not in supported_k:
		if row.get("blocker_kind") != "runtime_suffix_k_not_implemented":
			errors.append(f"{prefix} unsupported K requires blocker_kind=runtime_suffix_k_not_implemented")
		if str(row.get("blocker_detail", "") or "").strip() == "":
			errors.append(f"{prefix} unsupported K requires blocker_detail")


def validate_report(obj: dict[str, Any]) -> dict[str, Any]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	for field in REQUIRED_TOP:
		if field not in obj:
			errors.append(f"missing required field: {field}")
	k_values = _int_list(obj.get("k_values_tested_or_classified"))
	supported = _int_list(obj.get("runtime_supported_k"))
	idle_slots = _int_list(obj.get("idle_extra_rows_swept"))
	if k_values is None or not k_values:
		errors.append("k_values_tested_or_classified must be a non-empty int list")
		k_values = []
	if supported is None:
		errors.append("runtime_supported_k must be an int list")
		supported = []
	if idle_slots is None or not idle_slots:
		errors.append("idle_extra_rows_swept must be a non-empty int list")
		idle_slots = []
	if obj.get("k_power_of_two_required") is not False:
		errors.append("k_power_of_two_required must be false")
	if k_values and all(is_power_of_two(k) for k in k_values):
		errors.append("sweep must include at least one non-power-of-two K")
	accept_prob = _num(obj.get("accept_prob_used_for_projection"))
	if accept_prob is None or accept_prob < 0.0 or accept_prob > 1.0:
		errors.append("accept_prob_used_for_projection must be in [0,1]")
	rows = obj.get("k_results")
	if not isinstance(rows, list) or not rows:
		errors.append("k_results must be a non-empty list")
		rows = []
	if [row.get("k") for row in rows if isinstance(row, dict)] != k_values:
		errors.append("k_results K order must match k_values_tested_or_classified")
	for index, row in enumerate(rows):
		validate_row(errors, row, idle_slots, set(supported), index)
	refs = obj.get("reference_measurements")
	if not isinstance(refs, list):
		errors.append("reference_measurements must be a list")
		refs = []
	for index, ref in enumerate(refs):
		if not isinstance(ref, dict):
			errors.append(f"reference_measurements[{index}] must be an object")
			continue
		validate_measured(errors, ref, f"reference_measurements[{index}]")
	if obj.get("blocker_kind") == "candidate_k_runtime_not_implemented" and not refs:
		errors.append("candidate_k_runtime_not_implemented requires reference_measurements")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	return {"ok": len(errors) == 0, "errors": errors}


def main(argv: Optional[list[str]] = None) -> int:
	ap = ArgumentParser()
	ap.add_argument("paths", nargs="+")
	args = ap.parse_args(argv)
	ok = True
	results: dict[str, Any] = {}
	for raw in args.paths:
		obj = json.loads(Path(raw).read_text(encoding="utf-8"))
		res = validate_report(obj)
		results[raw] = res
		ok = ok and bool(res.get("ok"))
	print(json.dumps(results if len(results) != 1 else next(iter(results.values())), indent=2, sort_keys=True))
	return 0 if ok else 1


if __name__ == "__main__":
	raise SystemExit(main())
