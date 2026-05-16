#!/usr/bin/env python3
"""Validate DS4 stage handoff truth artifacts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


FORMAT = "ds4-stage-handoff-truth-v1"


def load_json(path: Path) -> dict[str, Any]:
	try:
		with path.open("r", encoding="utf-8") as f:
			obj = json.load(f)
	except (OSError, json.JSONDecodeError) as e:
		raise SystemExit(f"error: failed to read {path}: {e}") from e
	if not isinstance(obj, dict):
		raise SystemExit(f"error: {path}: expected JSON object")
	return obj


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append("missing or invalid format")
	for key in [
		"run_id",
		"model_id",
		"runtime_id",
		"quantization_id",
		"batch_size",
		"stage_count",
		"layer_ranges",
		"boundary_layout",
		"boundary_dtype",
		"boundary_bytes",
		"stage_ms",
		"final_logits_hash",
		"final_output_finite",
		"pipeline_rows_per_s_bound",
		"blocker_kind",
		"blocker_detail",
	]:
		if key not in obj:
			errors.append(f"missing required field: {key}")
	for key in ["spark_count", "num_sparks", "world_size"]:
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	stage_count = obj.get("stage_count")
	stage_ms = obj.get("stage_ms")
	layer_ranges = obj.get("layer_ranges")
	batch = obj.get("batch_size")
	if not isinstance(stage_count, int) or stage_count <= 0:
		errors.append("stage_count must be a positive integer")
	if not isinstance(stage_ms, list) or not isinstance(stage_count, int) or len(stage_ms) != stage_count:
		errors.append("stage_ms length must match stage_count")
	if not isinstance(layer_ranges, list) or not isinstance(stage_count, int) or len(layer_ranges) != stage_count:
		errors.append("layer_ranges length must match stage_count")
	if isinstance(layer_ranges, list):
		last_end = None
		for idx, item in enumerate(layer_ranges):
			if not isinstance(item, list) or len(item) != 2 or not all(isinstance(v, int) for v in item):
				errors.append(f"layer_ranges[{idx}] must be [begin,end]")
				continue
			if item[0] >= item[1]:
				errors.append(f"layer_ranges[{idx}] must be non-empty")
			if last_end is not None and item[0] != last_end:
				errors.append("layer ranges must be contiguous")
			last_end = item[1]
	if obj.get("boundary_dtype") != "f32":
		errors.append("boundary_dtype must be f32 for the current handoff hook")
	if not isinstance(obj.get("boundary_bytes"), int) or obj.get("boundary_bytes", 0) <= 0:
		errors.append("boundary_bytes must be positive")
	if obj.get("final_output_finite") is True:
		logits_hash = obj.get("final_logits_hash")
		if not isinstance(logits_hash, str) or not logits_hash.startswith("fnv64:") or logits_hash.endswith("0000000000000000"):
			errors.append("finite final output requires a non-zero fnv64 final_logits_hash")
		if obj.get("blocker_kind") != "none":
			errors.append("successful handoff must use blocker_kind=none")
	else:
		if obj.get("blocker_kind") in (None, "", "none"):
			errors.append("failed handoff requires a blocker_kind")
	if obj.get("streaming_pipeline") is not True and isinstance(stage_ms, list) and all(isinstance(v, (int, float)) and v > 0 for v in stage_ms):
		bound = obj.get("pipeline_rows_per_s_bound")
		if isinstance(batch, int) and batch > 0 and isinstance(bound, (int, float)):
			expected = batch * 1000.0 / max(float(v) for v in stage_ms)
			if not math.isclose(float(bound), expected, rel_tol=0.001, abs_tol=0.001):
				errors.append("pipeline_rows_per_s_bound does not match slowest stage")
	if obj.get("streaming_pipeline") is True:
		if obj.get("transport_kind") != "tcp_binary":
			errors.append("streaming handoff requires transport_kind=tcp_binary")
		microbatches = obj.get("microbatch_count")
		depth = obj.get("pipeline_depth")
		if not isinstance(microbatches, int) or microbatches <= 0:
			errors.append("streaming handoff requires positive microbatch_count")
		if not isinstance(depth, int) or depth <= 0:
			errors.append("streaming handoff requires positive pipeline_depth")
		if isinstance(microbatches, int) and isinstance(depth, int) and depth > microbatches:
			errors.append("pipeline_depth must not exceed microbatch_count")
		for key in ["achieved_streaming_rows_per_s", "bubble_overhead_ratio"]:
			if not isinstance(obj.get(key), (int, float)):
				errors.append(f"streaming handoff requires numeric {key}")
		for key in [
			"steady_state_rows_per_s",
			"observed_steady_state_rows_per_s",
			"steady_state_microbatch_interval_ms",
			"steady_state_pipeline_bound_rows_per_s",
			"fill_ms",
			"drain_ms",
			"slowest_resource_service_ms",
			"stage_balance_ratio",
		]:
			if key in obj and not isinstance(obj.get(key), (int, float)):
				errors.append(f"streaming handoff {key} must be numeric when present")
		if "stage_balance_ratio" in obj and isinstance(obj.get("stage_balance_ratio"), (int, float)) and obj["stage_balance_ratio"] < 0:
			errors.append("stage_balance_ratio must be non-negative")
		if "steady_state_window_microbatches" in obj:
			window = obj.get("steady_state_window_microbatches")
			if not isinstance(window, list) or not all(isinstance(v, int) for v in window):
				errors.append("steady_state_window_microbatches must be a list of integers")
		if "slowest_resource_kind" in obj and obj.get("slowest_resource_kind") not in ("", "stage_compute", "boundary_transfer"):
			errors.append("slowest_resource_kind must be stage_compute or boundary_transfer when present")
		if "slowest_resource_id" in obj and obj.get("slowest_resource_id") is not None and not isinstance(obj.get("slowest_resource_id"), int):
			errors.append("slowest_resource_id must be an integer or null")
		if "slowest_stage_id" in obj and obj.get("slowest_stage_id") is not None:
			if not isinstance(obj.get("slowest_stage_id"), int):
				errors.append("slowest_stage_id must be an integer or null")
			elif isinstance(stage_count, int) and not (0 <= obj["slowest_stage_id"] < stage_count):
				errors.append("slowest_stage_id must be within stage_count")
		transfers = obj.get("transfer_ms_by_boundary")
		if not isinstance(transfers, list) or not isinstance(stage_count, int) or len(transfers) != max(stage_count - 1, 0):
			errors.append("transfer_ms_by_boundary length must match stage_count-1")
		elif isinstance(microbatches, int) and obj.get("final_output_finite") is True:
			for idx, link in enumerate(transfers):
				if not isinstance(link, list) or len(link) != microbatches:
					errors.append(f"transfer_ms_by_boundary[{idx}] length must match microbatch_count")
				elif not all(isinstance(v, (int, float)) and v >= 0 for v in link):
					errors.append(f"transfer_ms_by_boundary[{idx}] must contain non-negative numbers")
		hashes = obj.get("final_logits_hashes")
		if obj.get("final_output_finite") is True and (not isinstance(hashes, list) or not isinstance(microbatches, int) or len(hashes) != microbatches):
			errors.append("final_logits_hashes length must match microbatch_count")
		elif obj.get("final_output_finite") is True and not all(isinstance(v, str) and v.startswith("fnv64:") and not v.endswith("0000000000000000") for v in hashes):
			errors.append("final_logits_hashes must contain non-zero fnv64 hashes")
		if "committed_token_ids_present" in obj:
			ids_present = obj.get("committed_token_ids_present")
			ids_obj = obj.get("committed_token_ids")
			if not isinstance(ids_present, bool):
				errors.append("committed_token_ids_present must be boolean")
			elif ids_present != (isinstance(ids_obj, list) and len(ids_obj) > 0):
				errors.append("committed_token_ids_present must match committed_token_ids list presence")
			if obj.get("committed_token_ids_present") is True:
				ids = obj.get("committed_token_ids")
				if not isinstance(ids, list) or not isinstance(batch, int) or len(ids) != batch:
					errors.append("committed_token_ids length must match batch_size when present")
				elif not all(isinstance(v, int) and v >= 0 for v in ids):
					errors.append("committed_token_ids must contain non-negative integers")
				token_hash = obj.get("token_hash")
				if not isinstance(token_hash, str) or not token_hash.startswith("fnv64:") or token_hash.endswith("0000000000000000"):
					errors.append("token_hash must be a non-zero fnv64 hash when committed tokens are present")
				commit_ms = obj.get("token_commit_ms_by_microbatch")
				if not isinstance(commit_ms, list) or not isinstance(microbatches, int) or len(commit_ms) != microbatches:
					errors.append("token_commit_ms_by_microbatch length must match microbatch_count when committed tokens are present")
				elif not all(isinstance(v, (int, float)) and v >= 0 for v in commit_ms):
					errors.append("token_commit_ms_by_microbatch must contain non-negative numbers")
				if "token_commit_profile" in obj:
					profile = obj.get("token_commit_profile")
					if not isinstance(profile, dict):
						errors.append("token_commit_profile must be an object when present")
					elif profile.get("format") != "ds4-token-commit-profile-v1":
						errors.append("token_commit_profile format must be ds4-token-commit-profile-v1")
					else:
						for key in ("stage2_final_hidden_output_ms", "output_head_ms", "top1_argmax_ms", "logits_readback_ms", "token_id_readback_ms", "token_hash_ms", "result_collection_ms", "synchronization_wait_ms"):
							values = profile.get(key)
							if not isinstance(values, list) or not isinstance(microbatches, int) or len(values) != microbatches:
								errors.append(f"token_commit_profile {key} length must match microbatch_count")
							elif not all(isinstance(v, (int, float)) and v >= 0 for v in values):
								errors.append(f"token_commit_profile {key} must contain non-negative numbers")
		if "row_token_input" in obj:
			if not isinstance(obj.get("row_token_input"), bool):
				errors.append("row_token_input must be boolean when present")
			if obj.get("row_token_input") is True:
				if obj.get("row_token_count") != batch:
					errors.append("row_token_count must match batch_size when row_token_input=true")
				if not isinstance(obj.get("row_token_ids_sha256"), str) or not obj.get("row_token_ids_sha256", "").startswith("sha256:"):
					errors.append("row_token_ids_sha256 must be sha256 when row_token_input=true")
				compact = obj.get("compact_suffix_token_ids")
				if not isinstance(compact, list) or not compact or not all(isinstance(v, int) and v >= 0 for v in compact):
					errors.append("compact_suffix_token_ids must be a non-empty list when row_token_input=true")
		if obj.get("parity_scope") not in (None, "stage_handoff_finite_logits"):
			errors.append("streaming handoff parity_scope must be stage_handoff_finite_logits when present")
		if obj.get("parity_status") not in (None, "not_run"):
			errors.append("streaming handoff parity_status must remain not_run")
		if obj.get("parity_blocker") not in (None, "missing_repo_owned_split_forward_runtime_hook"):
			errors.append("streaming handoff parity_blocker must identify the missing split-forward hook when present")
		if obj.get("production_generation_eligible") is True:
			errors.append("stage handoff proof must not claim production_generation_eligible")
		stage_iters = obj.get("stage_ms_by_microbatch")
		bound = obj.get("pipeline_rows_per_s_bound")
		batch = obj.get("batch_size")
		if (
			isinstance(stage_iters, list)
			and isinstance(transfers, list)
			and isinstance(batch, int)
			and batch > 0
			and isinstance(bound, (int, float))
			and obj.get("final_output_finite") is True
		):
			service: list[float] = []
			for idx, values in enumerate(stage_iters):
				if not isinstance(values, list):
					errors.append(f"stage_ms_by_microbatch[{idx}] must be a list")
					continue
				for mb, value in enumerate(values):
					if not isinstance(value, (int, float)) or value <= 0:
						errors.append(f"stage_ms_by_microbatch[{idx}][{mb}] must be positive")
						continue
					total = float(value)
					if idx + 1 < len(stage_iters) and isinstance(transfers[idx], list) and mb < len(transfers[idx]):
						total += float(transfers[idx][mb])
					service.append(total)
			if service:
				expected = batch * 1000.0 / max(service)
				if not math.isclose(float(bound), expected, rel_tol=0.001, abs_tol=0.001):
					errors.append("pipeline_rows_per_s_bound does not match streaming service bottleneck")
	return errors


def main() -> None:
	ap = argparse.ArgumentParser()
	ap.add_argument("paths", nargs="+")
	args = ap.parse_args()
	failed = False
	for raw in args.paths:
		path = Path(raw)
		obj = load_json(path)
		errors = validate_artifact(obj)
		if errors:
			failed = True
			for error in errors:
				print(f"error: {path}: {error}", file=sys.stderr)
		else:
			print(f"ok: {path}")
	if failed:
		raise SystemExit(2)


if __name__ == "__main__":
	main()
