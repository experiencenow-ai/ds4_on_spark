#!/usr/bin/env python3
"""Validate DS4 vLLM MXFP4 MoE code-audit artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts._lib.json_utils import canonical_hash, load_json, make_validate_paths


FORMAT = "ds4-vllm-moe-code-audit-v1"
REQUIRED_EVIDENCE_IDS = {
	"backend_priority_order",
	"backend_auto_selection",
	"no_dp_ep_standard_activation",
	"batched_activation_gating",
	"batched_marlin_exists",
	"deepseek_v4_fused_moe_normal_path",
	"deepseek_v4_lm_head_full_logits",
	"logits_processor_top_tokens_unused_normal",
	"mxfp4_w13_shape",
	"ds4_slice_tile8_mechanism",
}
REQUIRED_OPPORTUNITY_IDS = {
	"enable_batched_activation_for_no_dp_ep",
	"capture_explicit_deep_gemm_flashinfer_rejection",
	"candidate_only_logits_for_constrained_outputs",
	"copy_ds4_slice_tile8_kernel_directly",
}


def default_paths() -> list[Path]:
	root = Path(__file__).resolve().parents[1]
	return(sorted((root / "fixtures" / "vllm_moe_code_audit").glob("*.example.json")))


def err(path: Path, msg: str) -> str:
	return(f"{path}: {msg}")


def load(path: Path) -> dict[str, Any]:
	return(load_json(path, "root JSON"))


def ids_from_items(items: Any) -> set[str]:
	result: set[str] = set()
	if not isinstance(items, list):
		return(result)
	for item in items:
		if isinstance(item, dict) and isinstance(item.get("id"), str):
			result.add(item["id"])
	return(result)


def validate_source_evidence(obj: dict[str, Any], path: Path, errors: list[str]) -> None:
	items = obj.get("source_evidence")
	if not isinstance(items, list) or len(items) == 0:
		errors.append(err(path, "source_evidence must be a non-empty list"))
		return
	missing = sorted(REQUIRED_EVIDENCE_IDS - ids_from_items(items))
	if missing:
		errors.append(err(path, "source_evidence missing ids: " + ",".join(missing)))
	for item in items:
		if not isinstance(item, dict):
			errors.append(err(path, "each source_evidence item must be an object"))
			continue
		for field in ("id", "file", "finding"):
			if not isinstance(item.get(field), str) or item[field] == "":
				errors.append(err(path, f"source_evidence item missing {field}"))
		if not isinstance(item.get("line_start"), int) or not isinstance(item.get("line_end"), int):
			errors.append(err(path, "source_evidence line_start/line_end must be integers"))
		elif item["line_end"] < item["line_start"]:
			errors.append(err(path, "source_evidence line_end must be >= line_start"))


def validate_opportunities(obj: dict[str, Any], path: Path, errors: list[str]) -> None:
	items = obj.get("opportunities")
	if not isinstance(items, list) or len(items) == 0:
		errors.append(err(path, "opportunities must be a non-empty list"))
		return
	missing = sorted(REQUIRED_OPPORTUNITY_IDS - ids_from_items(items))
	if missing:
		errors.append(err(path, "opportunities missing ids: " + ",".join(missing)))
		return
	status_by_id: dict[str, str] = {}
	for item in items:
		if not isinstance(item, dict):
			errors.append(err(path, "each opportunity item must be an object"))
			continue
		item_id = item.get("id")
		status = item.get("status")
		if not isinstance(item_id, str):
			errors.append(err(path, "opportunity id must be a string"))
			continue
		if status not in {"reachable", "blocked", "not_portable", "measured_absent"}:
			errors.append(err(path, f"opportunity {item_id} has invalid status"))
			continue
		status_by_id[item_id] = status
		if not isinstance(item.get("next_action"), str) or item["next_action"] == "":
			errors.append(err(path, f"opportunity {item_id} missing next_action"))
	if status_by_id.get("copy_ds4_slice_tile8_kernel_directly") != "not_portable":
		errors.append(err(path, "copy_ds4_slice_tile8_kernel_directly must be marked not_portable"))
	if status_by_id.get("enable_batched_activation_for_no_dp_ep") != "reachable":
		errors.append(err(path, "enable_batched_activation_for_no_dp_ep must be marked reachable"))
	if status_by_id.get("candidate_only_logits_for_constrained_outputs") != "measured_absent":
		errors.append(err(path, "candidate_only_logits_for_constrained_outputs must be marked measured_absent"))


def validate(obj: dict[str, Any], path: Path) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != FORMAT:
		errors.append(err(path, f"format must be {FORMAT}"))
	if obj.get("artifact_sha256") != canonical_hash(obj):
		errors.append(err(path, "artifact_sha256 does not match canonical hash"))
	if obj.get("measured_selected_backend") != "MARLIN":
		errors.append(err(path, "measured_selected_backend must be MARLIN for this audit"))
	if not isinstance(obj.get("runtime_commit"), str) or obj["runtime_commit"] == "":
		errors.append(err(path, "runtime_commit must be a non-empty string"))
	if not isinstance(obj.get("runtime_version"), str) or obj["runtime_version"] == "":
		errors.append(err(path, "runtime_version must be a non-empty string"))
	validate_source_evidence(obj, path, errors)
	validate_opportunities(obj, path, errors)
	recommended = obj.get("recommended_next_experiment")
	if not isinstance(recommended, str) or recommended == "":
		errors.append(err(path, "recommended_next_experiment must be a non-empty string"))
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
