#!/usr/bin/env python3
"""Validate DS4 vLLM no-DP BatchedMarlin prototype artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._lib.json_utils import canonical_hash, load_json, make_validate_paths


FORMAT = "ds4-vllm-no-dp-batched-marlin-prototype-v1"
REQUIRED_PATCH_FILES = {
	"vllm/model_executor/layers/fused_moe/config.py",
	"vllm/model_executor/layers/fused_moe/all2all_utils.py",
	"vllm/model_executor/layers/fused_moe/prepare_finalize/batched.py",
	"vllm/model_executor/layers/fused_moe/topk_weight_and_reduce.py",
}


def default_paths() -> list[Path]:
	root = Path(__file__).resolve().parents[1]
	return(sorted((root / "fixtures" / "vllm_no_dp_batched_marlin").glob("*.example.json")))


def err(path: Path, msg: str) -> str:
	return(f"{path}: {msg}")


def load(path: Path) -> dict[str, Any]:
	return(load_json(path, "root JSON"))


def validate_patch_files(obj: dict[str, Any], path: Path, errors: list[str]) -> None:
	files = obj.get("patch_files")
	if not isinstance(files, list):
		errors.append(err(path, "patch_files must be a list"))
		return
	seen = {item for item in files if isinstance(item, str)}
	missing = sorted(REQUIRED_PATCH_FILES - seen)
	if missing:
		errors.append(err(path, "patch_files missing: " + ",".join(missing)))


def validate_measurement(obj: dict[str, Any], path: Path, errors: list[str]) -> None:
	baseline = obj.get("baseline_c512_aggregate_tps")
	measured = obj.get("measured_c512_aggregate_tps")
	speedup = obj.get("speedup_vs_baseline")
	if not isinstance(baseline, (int, float)) or baseline <= 0:
		errors.append(err(path, "baseline_c512_aggregate_tps must be positive"))
		return
	status = obj.get("startup_status")
	if status == "passed":
		if not isinstance(measured, (int, float)) or measured <= 0:
			errors.append(err(path, "passed startup requires measured_c512_aggregate_tps"))
		if not isinstance(speedup, (int, float)) or speedup <= 0:
			errors.append(err(path, "passed startup requires speedup_vs_baseline"))
		elif isinstance(measured, (int, float)) and abs(speedup - (measured / baseline)) > 0.0001:
			errors.append(err(path, "speedup_vs_baseline must match measured/baseline"))
	elif status == "failed":
		if obj.get("blocker_kind") in (None, ""):
			errors.append(err(path, "failed startup requires blocker_kind"))
		if obj.get("blocker_detail") in (None, ""):
			errors.append(err(path, "failed startup requires blocker_detail"))
		if obj.get("error_signature") in (None, ""):
			errors.append(err(path, "failed startup requires error_signature"))
		if measured is not None:
			errors.append(err(path, "failed startup must not report measured_c512_aggregate_tps"))
	else:
		errors.append(err(path, "startup_status must be passed or failed"))


def validate(obj: dict[str, Any], path: Path) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(err(path, f"format must be {FORMAT}"))
	if obj.get("artifact_sha256") != canonical_hash(obj):
		errors.append(err(path, "artifact_sha256 does not match canonical hash"))
	for field in ("prototype_id", "model_id", "runtime_version", "runtime_commit", "patch_id"):
		if not isinstance(obj.get(field), str) or obj[field] == "":
			errors.append(err(path, f"{field} must be a non-empty string"))
	if obj.get("env_flag") != "DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1":
		errors.append(err(path, "env_flag must be DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1"))
	if obj.get("selected_backend") != "BATCHED_MARLIN":
		errors.append(err(path, "selected_backend must be BATCHED_MARLIN"))
	if obj.get("activation_format") != "BatchedExperts":
		errors.append(err(path, "activation_format must be BatchedExperts"))
	if obj.get("prepare_finalize") != "BatchedPrepareAndFinalize":
		errors.append(err(path, "prepare_finalize must be BatchedPrepareAndFinalize"))
	validate_patch_files(obj, path, errors)
	validate_measurement(obj, path, errors)
	return(errors)


validate_paths = make_validate_paths(validate, load)


def main() -> int:
	p = argparse.ArgumentParser(description=__doc__)
	p.add_argument("paths", nargs="*", type=Path)
	args = p.parse_args()
	paths = args.paths if args.paths else default_paths()
	result = validate_paths(paths)
	print(json.dumps(result, indent=2, sort_keys=True))
	return(0 if result["ok"] else 1)


if __name__ == "__main__":
	raise SystemExit(main())
