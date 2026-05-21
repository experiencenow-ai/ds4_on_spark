#!/usr/bin/env python3
"""Validate DS4 GB10 FlashInfer TRTLLM MXFP4 MoE probe artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-gb10-flashinfer-moe-probe-v1"
HASH_FIELDS = {"artifact_sha256"}
PATCH_FILE = "vllm/model_executor/layers/fused_moe/experts/trtllm_mxfp4_moe.py"


def default_paths() -> list[Path]:
	root = Path(__file__).resolve().parents[1]
	return(sorted((root / "fixtures" / "vllm_gb10_flashinfer_moe").glob("*.example.json")))


def canonical_hash(obj: dict[str, Any]) -> str:
	payload = copy.deepcopy(obj)
	for field in HASH_FIELDS:
		payload.pop(field, None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
	return(hashlib.sha256(data).hexdigest())


def err(path: Path, msg: str) -> str:
	return(f"{path}: {msg}")


def load(path: Path) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as f:
		obj = json.load(f)
	if not isinstance(obj, dict):
		raise ValueError("root JSON must be an object")
	return(obj)


def validate(obj: dict[str, Any], path: Path) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(err(path, f"format must be {FORMAT}"))
	if obj.get("artifact_sha256") != canonical_hash(obj):
		errors.append(err(path, "artifact_sha256 does not match canonical hash"))
	for field in ("probe_id", "model_id", "runtime_version", "runtime_commit", "patch_id"):
		if not isinstance(obj.get(field), str) or obj[field] == "":
			errors.append(err(path, f"{field} must be a non-empty string"))
	if obj.get("env_flag") != "DS4_VLLM_ENABLE_GB10_FLASHINFER_TRTLLM_MOE=1":
		errors.append(err(path, "env_flag must be DS4_VLLM_ENABLE_GB10_FLASHINFER_TRTLLM_MOE=1"))
	files = obj.get("patch_files")
	if not isinstance(files, list) or PATCH_FILE not in files:
		errors.append(err(path, f"patch_files must include {PATCH_FILE}"))
	if obj.get("device_name") != "NVIDIA GB10":
		errors.append(err(path, "device_name must be NVIDIA GB10"))
	if obj.get("device_capability") != [12, 1]:
		errors.append(err(path, "device_capability must be [12, 1]"))
	for field in ("flashinfer_available", "supports_trtllm_mxfp4_after_patch"):
		if obj.get(field) is not True:
			errors.append(err(path, f"{field} must be true"))
	if obj.get("platform_family100_before_patch") is not False:
		errors.append(err(path, "platform_family100_before_patch must be false for GB10"))
	status = obj.get("startup_status")
	if status == "passed":
		baseline = obj.get("baseline_c512_aggregate_tps")
		measured = obj.get("measured_c512_aggregate_tps")
		if not isinstance(baseline, (int, float)) or baseline <= 0:
			errors.append(err(path, "passed startup requires positive baseline_c512_aggregate_tps"))
		if not isinstance(measured, (int, float)) or measured <= 0:
			errors.append(err(path, "passed startup requires measured_c512_aggregate_tps"))
	elif status in ("not_run", "failed"):
		if obj.get("blocker_kind") in (None, ""):
			errors.append(err(path, "not_run/failed startup requires blocker_kind"))
		if obj.get("blocker_detail") in (None, ""):
			errors.append(err(path, "not_run/failed startup requires blocker_detail"))
	else:
		errors.append(err(path, "startup_status must be passed, failed, or not_run"))
	return(errors)


def validate_paths(paths: list[Path]) -> dict[str, Any]:
	all_errors: list[str] = []
	for path in paths:
		try:
			all_errors.extend(validate(load(path), path))
		except Exception as e:
			all_errors.append(err(path, str(e)))
	return({"ok": len(all_errors) == 0, "errors": all_errors})


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
