#!/usr/bin/env python3
"""Validate DS4 layer-pipeline parity artifacts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
	from scripts._lib.json_utils import artifact_sha256
	from scripts._lib.json_utils import is_sha256_text
	from scripts._lib.json_utils import load_json
except ImportError:
	from _lib.json_utils import artifact_sha256
	from _lib.json_utils import is_sha256_text
	from _lib.json_utils import load_json


FORMAT = "ds4-layer-pipeline-parity-v1"
SCHEMA_VERSION = 1
PARITY_STATUS = {"not_run", "passed", "failed"}
COMPARISON_KINDS = {"logits", "tokens", "hidden_state", "synthetic_integrity"}
QUALITY_COMPARISON_KINDS = {"logits", "tokens", "hidden_state"}
PARITY_SCOPES = {
	"cross_spark_ppn",
	"parity_passed_prefill_decode",
	"local_split_forward",
	"local_stage_reassembly",
	"local_ppn_emulated",
	"synthetic_integrity",
}
QUALITY_PARITY_SCOPES = {"cross_spark_ppn", "parity_passed_prefill_decode"}
FIXED_SPARK_COUNT_FIELDS = {"spark_count", "num_sparks", "world_size"}
REQUIRED = (
	"format",
	"artifact_schema_version",
	"artifact_sha256",
	"parity_run_id",
	"parity_scope",
	"provider_id",
	"pipeline_id",
	"model_id",
	"runtime_id",
	"tokenizer_sha256",
	"tokenizer_id",
	"tokenizer_hash_status",
	"quantization_id",
	"stage_count",
	"stage_manifest_sha256",
	"stage_inventory",
	"layer_ranges",
	"boundary_state_layout",
	"boundary_after_layers",
	"input_tokens_sha256",
	"pp1_output_sha256",
	"ppn_output_sha256",
	"comparison_kind",
	"parity_status",
	"quality_parity_eligible",
	"optimized_kernel_flags",
	"tolerance",
	"max_abs_error",
	"mean_abs_error",
	"token_match_count",
	"token_total_count",
	"quality_parity_detail",
	"blocker_detail",
	"command_sha256",
	"artifact_refs",
)


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_number(value: Any) -> bool:
	return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def add_missing_required(obj: dict[str, Any], errors: list[str]) -> None:
	for key in REQUIRED:
		if key not in obj:
			errors.append(f"missing required field: {key}")


def validate_identity(obj: dict[str, Any], errors: list[str]) -> None:
	for key in ("parity_run_id", "provider_id", "pipeline_id", "model_id", "runtime_id", "quantization_id"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	tokenizer_sha = obj.get("tokenizer_sha256", "")
	tokenizer_id = obj.get("tokenizer_id", "")
	tokenizer_hash_status = obj.get("tokenizer_hash_status", "")
	if not is_sha256_text(tokenizer_sha, allow_empty=True):
		errors.append("tokenizer_sha256 must be empty or sha256:<hex>")
	if tokenizer_sha == "" and (not isinstance(tokenizer_id, str) or tokenizer_id.strip() == "" or not isinstance(tokenizer_hash_status, str) or tokenizer_hash_status.strip() == ""):
		errors.append("tokenizer identity requires tokenizer_sha256 or tokenizer_id plus tokenizer_hash_status")
	for key in ("stage_manifest_sha256", "input_tokens_sha256", "command_sha256"):
		if not is_sha256_text(obj.get(key)):
			errors.append(f"{key} must be sha256:<hex>")


def validate_stage_shape(obj: dict[str, Any], errors: list[str]) -> None:
	stage_count = obj.get("stage_count")
	if not isinstance(stage_count, int) or isinstance(stage_count, bool) or stage_count <= 0:
		errors.append("stage_count must be a positive integer")
		stage_count = 0
	inventory = obj.get("stage_inventory")
	if not isinstance(inventory, list) or len(inventory) != stage_count:
		errors.append("stage_inventory must contain one entry per stage")
	layer_ranges = obj.get("layer_ranges")
	if not isinstance(layer_ranges, list) or len(layer_ranges) != stage_count:
		errors.append("layer_ranges must contain one entry per stage")
	boundaries = obj.get("boundary_after_layers")
	if not isinstance(boundaries, list):
		errors.append("boundary_after_layers must be a list")
	layout = obj.get("boundary_state_layout")
	if not isinstance(layout, dict):
		errors.append("boundary_state_layout must be an object")
	else:
		for key in ("status", "dtype", "layout", "shape"):
			if key not in layout:
				errors.append(f"boundary_state_layout.{key} is required")


def validate_metrics(obj: dict[str, Any], errors: list[str]) -> None:
	status = obj.get("parity_status")
	kind = obj.get("comparison_kind")
	scope = obj.get("parity_scope")
	if status not in PARITY_STATUS:
		errors.append("parity_status must be not_run, passed, or failed")
	if kind not in COMPARISON_KINDS:
		errors.append("comparison_kind must be logits, tokens, hidden_state, or synthetic_integrity")
	if scope not in PARITY_SCOPES:
		errors.append("parity_scope must be one of the declared parity scopes")
	eligible = obj.get("quality_parity_eligible")
	if not isinstance(eligible, bool):
		errors.append("quality_parity_eligible must be boolean")
	if kind == "synthetic_integrity" and eligible is True:
		errors.append("synthetic_integrity cannot be marked quality_parity_eligible")
	if eligible is True:
		if status != "passed":
			errors.append("quality_parity_eligible requires parity_status=passed")
		if scope not in QUALITY_PARITY_SCOPES:
			errors.append("quality_parity_eligible requires cross_spark_ppn or parity_passed_prefill_decode scope")
		if kind not in QUALITY_COMPARISON_KINDS:
			errors.append("quality_parity_eligible requires logits, tokens, or hidden_state comparison")
	flags = obj.get("optimized_kernel_flags")
	if not isinstance(flags, dict):
		errors.append("optimized_kernel_flags must be an object")
	blocker = obj.get("blocker_detail", "")
	if status != "passed" and (not isinstance(blocker, str) or blocker.strip() == ""):
		errors.append("blocker_detail must explain non-passed parity")
	for key in ("pp1_output_sha256", "ppn_output_sha256"):
		value = obj.get(key)
		if not is_sha256_text(value, allow_empty=True):
			errors.append(f"{key} must be empty or sha256:<hex>")
		if value == "" and (not isinstance(blocker, str) or blocker.strip() == ""):
			errors.append(f"{key} requires blocker_detail when absent")
	if status in ("passed", "failed"):
		for key in ("pp1_output_sha256", "ppn_output_sha256"):
			if not is_sha256_text(obj.get(key)):
				errors.append(f"{key} must be sha256:<hex> when parity was run")
	if status == "passed":
		if kind == "synthetic_integrity":
			return
		for key in ("max_abs_error", "mean_abs_error"):
			if not is_number(obj.get(key)):
				errors.append(f"{key} must be numeric for passed parity")
		tol = obj.get("tolerance")
		if not isinstance(tol, dict):
			errors.append("tolerance must be an object")
			return
		for key in ("max_abs_error", "mean_abs_error"):
			if not is_number(tol.get(key)):
				errors.append(f"tolerance.{key} must be numeric for passed parity")
		if is_number(obj.get("max_abs_error")) and is_number(tol.get("max_abs_error")) and float(obj["max_abs_error"]) > float(tol["max_abs_error"]):
			errors.append("max_abs_error exceeds tolerance")
		if is_number(obj.get("mean_abs_error")) and is_number(tol.get("mean_abs_error")) and float(obj["mean_abs_error"]) > float(tol["mean_abs_error"]):
			errors.append("mean_abs_error exceeds tolerance")
		total = obj.get("token_total_count")
		match = obj.get("token_match_count")
		if not isinstance(total, int) or isinstance(total, bool) or total <= 0:
			errors.append("token_total_count must be > 0 for passed parity")
		if not isinstance(match, int) or isinstance(match, bool) or match < 0 or (isinstance(total, int) and match > total):
			errors.append("token_match_count must be in [0, token_total_count]")
		if kind == "tokens" and isinstance(total, int) and isinstance(match, int) and match != total:
			errors.append("tokens parity requires token_match_count == token_total_count")


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	add_missing_required(obj, errors)
	for key in FIXED_SPARK_COUNT_FIELDS:
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	if obj.get("artifact_schema_version") != SCHEMA_VERSION:
		errors.append(f"artifact_schema_version must be {SCHEMA_VERSION}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	validate_identity(obj, errors)
	validate_stage_shape(obj, errors)
	validate_metrics(obj, errors)
	if not isinstance(obj.get("quality_parity_detail"), str) or obj.get("quality_parity_detail", "").strip() == "":
		errors.append("quality_parity_detail must be a non-empty string")
	if not isinstance(obj.get("artifact_refs"), list):
		errors.append("artifact_refs must be a list")
	return errors


def is_quality_parity_pass(obj: dict[str, Any]) -> bool:
	return (
		obj.get("format") == FORMAT
		and obj.get("parity_status") == "passed"
		and obj.get("parity_scope") in QUALITY_PARITY_SCOPES
		and obj.get("comparison_kind") in QUALITY_COMPARISON_KINDS
		and obj.get("quality_parity_eligible") is True
		and len(validate_artifact(obj)) == 0
	)


def cmd_validate(paths: list[Path], fix_hash: bool) -> int:
	ok = True
	for path in paths:
		obj = load_json(path)
		if fix_hash:
			obj["artifact_sha256"] = artifact_sha256(obj)
			write_json(path, obj)
		errors = validate_artifact(obj)
		if errors:
			ok = False
			for item in errors:
				print(f"{path}: {item}")
		else:
			print(f"ok: {path}")
	return 0 if ok else 1


def main() -> int:
	parser = argparse.ArgumentParser(description="Validate ds4-layer-pipeline-parity-v1 artifacts.")
	parser.add_argument("artifacts", nargs="+")
	parser.add_argument("--fix-hash", action="store_true", help="Rewrite artifact_sha256 before validating.")
	args = parser.parse_args()
	return cmd_validate([Path(item) for item in args.artifacts], bool(args.fix_hash))


if __name__ == "__main__":
	raise SystemExit(main())
