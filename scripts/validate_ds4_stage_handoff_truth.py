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
	if isinstance(stage_ms, list) and all(isinstance(v, (int, float)) and v > 0 for v in stage_ms):
		batch = obj.get("batch_size")
		bound = obj.get("pipeline_rows_per_s_bound")
		if isinstance(batch, int) and batch > 0 and isinstance(bound, (int, float)):
			expected = batch * 1000.0 / max(float(v) for v in stage_ms)
			if not math.isclose(float(bound), expected, rel_tol=0.001, abs_tol=0.001):
				errors.append("pipeline_rows_per_s_bound does not match slowest stage")
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
