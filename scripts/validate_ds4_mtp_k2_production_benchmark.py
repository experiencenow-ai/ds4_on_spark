#!/usr/bin/env python3
"""Validate DS4 K=2 MTP production benchmark artifacts."""

from __future__ import annotations

import json
import math
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any


FORMAT = "ds4-mtp-k2-production-benchmark-v1"
TAIL_STATUSES = {"passed", "failed", "blocked", "not_run"}
TAIL_CASES = {"n_predict_mod_3_0", "n_predict_mod_3_1", "n_predict_mod_3_2"}

REQUIRED_STRINGS = (
	"run_id",
	"model_id",
	"runtime_id",
	"quantization_id",
	"prompt_id",
	"prompt_hash",
	"tail_case",
	"tail_acceptance_status",
	"suppress_output_mode",
	"blocker_kind",
	"blocker_detail",
)

REQUIRED_NUMBERS = (
	"baseline_tps",
	"mtp_tps",
	"speedup_vs_baseline",
	"accept_rate",
	"target_positions_per_invocation",
)

REQUIRED_INTS = (
	"n_predict",
	"accepted_draft_tokens",
	"attempted_draft_tokens",
	"target_next_mismatch_events",
	"verifier_invocation_count",
	"target_positions_verified",
	"output_head_invocation_count",
	"full_vocab_logits_rows",
	"top1_only_rows",
)


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	for key in REQUIRED_STRINGS:
		if not isinstance(obj.get(key), str) or str(obj.get(key)).strip() == "":
			errors.append(f"{key} must be a non-empty string")
	for key in REQUIRED_NUMBERS:
		if not isinstance(obj.get(key), (int, float)) or float(obj.get(key, -1.0)) < 0.0:
			errors.append(f"{key} must be a non-negative number")
	for key in REQUIRED_INTS:
		if not isinstance(obj.get(key), int) or int(obj.get(key, -1)) < 0:
			errors.append(f"{key} must be a non-negative integer")
	if not isinstance(obj.get("stdout_suppressed"), bool):
		errors.append("stdout_suppressed must be boolean")
	if "production_eligible" in obj and not isinstance(obj.get("production_eligible"), bool):
		errors.append("production_eligible must be boolean when present")
	if "production_blockers" in obj:
		blockers = obj.get("production_blockers")
		if not isinstance(blockers, list) or not all(isinstance(v, str) and v for v in blockers):
			errors.append("production_blockers must be a list of non-empty strings")
	n_predict = obj.get("n_predict")
	if isinstance(n_predict, int) and n_predict > 0:
		expected_tail = f"n_predict_mod_3_{n_predict % 3}"
		if obj.get("tail_case") != expected_tail:
			errors.append(f"tail_case must be {expected_tail}")
	if obj.get("tail_case") not in TAIL_CASES:
		errors.append(f"tail_case must be one of {sorted(TAIL_CASES)}")
	if obj.get("tail_acceptance_status") not in TAIL_STATUSES:
		errors.append(f"tail_acceptance_status must be one of {sorted(TAIL_STATUSES)}")
	baseline = float(obj.get("baseline_tps", 0.0)) if isinstance(obj.get("baseline_tps"), (int, float)) else 0.0
	mtp = float(obj.get("mtp_tps", 0.0)) if isinstance(obj.get("mtp_tps"), (int, float)) else 0.0
	speedup = obj.get("speedup_vs_baseline")
	if baseline > 0.0 and isinstance(speedup, (int, float)):
		if not math.isclose(float(speedup), mtp / baseline, rel_tol=0.0005, abs_tol=0.0005):
			errors.append("speedup_vs_baseline must equal mtp_tps / baseline_tps")
	accepted = obj.get("accepted_draft_tokens")
	attempted = obj.get("attempted_draft_tokens")
	accept_rate = obj.get("accept_rate")
	if isinstance(accepted, int) and isinstance(attempted, int):
		if accepted > attempted:
			errors.append("accepted_draft_tokens must be <= attempted_draft_tokens")
		if attempted > 0 and isinstance(accept_rate, (int, float)):
			if not math.isclose(float(accept_rate), float(accepted) / float(attempted), rel_tol=0.0005, abs_tol=0.0005):
				errors.append("accept_rate must equal accepted_draft_tokens / attempted_draft_tokens")
	invocations = obj.get("verifier_invocation_count")
	positions = obj.get("target_positions_verified")
	ppinv = obj.get("target_positions_per_invocation")
	if isinstance(invocations, int) and isinstance(positions, int) and isinstance(ppinv, (int, float)):
		if invocations > 0 and not math.isclose(float(ppinv), float(positions) / float(invocations), rel_tol=0.0005, abs_tol=0.0005):
			errors.append("target_positions_per_invocation must equal target_positions_verified / verifier_invocation_count")
	if (
		isinstance(obj.get("full_vocab_logits_rows"), int)
		and isinstance(obj.get("top1_only_rows"), int)
		and isinstance(positions, int)
		and int(obj["full_vocab_logits_rows"]) + int(obj["top1_only_rows"]) != int(positions)
		and obj.get("blocker_kind") == "none"
	):
		errors.append("full_vocab_logits_rows + top1_only_rows must match target_positions_verified")
	if obj.get("blocker_kind") == "none" and obj.get("target_next_mismatch_events") != 0:
		errors.append("unblocked benchmark requires target_next_mismatch_events=0")
	if obj.get("blocker_kind") != "none" and str(obj.get("blocker_detail", "")).strip() == "":
		errors.append("blocked benchmark requires blocker_detail")
	if obj.get("production_eligible") is True:
		if obj.get("blocker_kind") != "none":
			errors.append("production_eligible requires blocker_kind=none")
		if obj.get("tail_acceptance_status") != "passed":
			errors.append("production_eligible requires tail_acceptance_status=passed")
		if obj.get("target_next_mismatch_events") != 0:
			errors.append("production_eligible requires target_next_mismatch_events=0")
		if obj.get("benchmark_matrix_status") != "passed":
			errors.append("production_eligible requires benchmark_matrix_status=passed")
		if obj.get("accepted_draft_tokens") == 0:
			errors.append("production_eligible requires accepted draft tokens")
	return errors


def main() -> int:
	ap = ArgumentParser()
	ap.add_argument("paths", nargs="+")
	args = ap.parse_args()
	failed = False
	for raw in args.paths:
		path = Path(raw)
		try:
			errors = validate_artifact(load_json(path))
		except (OSError, ValueError, json.JSONDecodeError) as exc:
			errors = [str(exc)]
		if errors:
			failed = True
			for error in errors:
				print(f"error: {path}: {error}", file=sys.stderr)
		else:
			print(f"ok: {path}")
	return 2 if failed else 0


if __name__ == "__main__":
	raise SystemExit(main())
