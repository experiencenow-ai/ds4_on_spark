#!/usr/bin/env python3
"""Emit a local PP=N emulated DS4 parity artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

try:
	from scripts import ds4_stage_boundary_shape_probe as boundary_probe
	from scripts import validate_ds4_pipeline_parity as parity
	from scripts._lib.json_utils import load_json
except ImportError:
	import ds4_stage_boundary_shape_probe as boundary_probe
	import validate_ds4_pipeline_parity as parity
	from _lib.json_utils import load_json


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_text(text: str) -> str:
	return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def dependency_blocker() -> str:
	missing = [name for name in ("torch", "transformers") if importlib.util.find_spec(name) is None]
	if missing:
		return "local PP=N emulated split not run: missing Python runtime dependencies: " + ", ".join(missing)
	return "local PP=N emulated split not run: no repo-owned split-forward runtime hook exists yet"


def boundary_ref(path: str, artifact: dict[str, Any]) -> dict[str, str]:
	return {
		"name": "stage_boundary_shape",
		"path": path,
		"sha256": str(artifact.get("artifact_sha256", "")),
	}


def boundary_layout(artifact: dict[str, Any]) -> dict[str, Any]:
	return {
		"status": artifact.get("probe_status", "not_available"),
		"dtype": artifact.get("dtype", "unknown"),
		"layout": artifact.get("layout", "unknown"),
		"shape": artifact.get("observed_tensor_shape", "unknown"),
	}


def build_artifact(args: argparse.Namespace) -> dict[str, Any]:
	boundary_artifact = load_json(Path(args.boundary_artifact))
	boundary_errors = boundary_probe.validate_artifact(boundary_artifact)
	if boundary_errors:
		raise ValueError("boundary artifact is invalid: " + "; ".join(boundary_errors))
	stage_inventory = copy.deepcopy(boundary_artifact.get("stage_inventory", []))
	layer_ranges = copy.deepcopy(boundary_artifact.get("layer_ranges", []))
	boundaries = copy.deepcopy(boundary_artifact.get("boundary_after_layers", []))
	blocker = args.blocker_detail or dependency_blocker()
	status = args.parity_status
	if status == "auto":
		status = "not_run"
	command = {
		"probe": "local_ppn_emulated",
		"parity_run_id": args.parity_run_id,
		"parity_scope": getattr(args, "parity_scope", "local_ppn_emulated"),
		"boundary_artifact": args.boundary_artifact,
		"comparison_kind": args.comparison_kind,
		"parity_status": status,
		"input_tokens": args.input_tokens,
		"stage_inventory": stage_inventory,
		"layer_ranges": layer_ranges,
		"optimized_kernel_flags": getattr(args, "optimized_kernel_flags", {}),
	}
	pp1_hash = args.pp1_output_sha256
	ppn_hash = args.ppn_output_sha256
	artifact = {
		"format": parity.FORMAT,
		"artifact_schema_version": parity.SCHEMA_VERSION,
		"parity_run_id": args.parity_run_id,
		"parity_scope": getattr(args, "parity_scope", "local_ppn_emulated"),
		"provider_id": args.provider_id,
		"pipeline_id": args.pipeline_id,
		"model_id": boundary_artifact.get("model_id", args.model_id),
		"runtime_id": boundary_artifact.get("runtime_id", args.runtime_id),
		"tokenizer_sha256": args.tokenizer_sha256,
		"tokenizer_id": args.tokenizer_id,
		"tokenizer_hash_status": args.tokenizer_hash_status,
		"quantization_id": boundary_artifact.get("quantization_id", args.quantization_id),
		"stage_count": len(stage_inventory),
		"stage_manifest_sha256": sha256_obj({"stage_inventory": stage_inventory, "layer_ranges": layer_ranges, "boundary_after_layers": boundaries}),
		"stage_inventory": stage_inventory,
		"layer_ranges": layer_ranges,
		"boundary_state_layout": boundary_layout(boundary_artifact),
		"boundary_after_layers": boundaries,
		"input_tokens_sha256": sha256_text(args.input_tokens),
		"pp1_output_sha256": pp1_hash,
		"ppn_output_sha256": ppn_hash,
		"comparison_kind": args.comparison_kind,
		"parity_status": status,
		"quality_parity_eligible": bool(args.quality_parity_eligible and status == "passed" and args.comparison_kind != "synthetic_integrity"),
		"optimized_kernel_flags": getattr(args, "optimized_kernel_flags", {}),
		"tolerance": {
			"max_abs_error": args.tolerance_max_abs_error,
			"mean_abs_error": args.tolerance_mean_abs_error,
		},
		"max_abs_error": args.max_abs_error,
		"mean_abs_error": args.mean_abs_error,
		"token_match_count": args.token_match_count,
		"token_total_count": args.token_total_count,
		"quality_parity_detail": args.quality_parity_detail or blocker,
		"blocker_detail": blocker if status != "passed" else "",
		"command_sha256": sha256_obj(command),
		"artifact_refs": [boundary_ref(args.boundary_artifact, boundary_artifact)],
	}
	artifact["artifact_sha256"] = parity.artifact_sha256(artifact)
	return artifact


def main() -> int:
	parser = argparse.ArgumentParser(description="Emit a ds4-layer-pipeline-parity-v1 local PP=N probe artifact.")
	parser.add_argument("--boundary-artifact", required=True)
	parser.add_argument("--out", default="")
	parser.add_argument("--parity-run-id", default="dsv4-local-ppn-parity-not-run-example")
	parser.add_argument("--provider-id", default="spark-ring-dsv4-layer-pipeline")
	parser.add_argument("--pipeline-id", default="spark012-ds4-layer-pipeline-local-ppn")
	parser.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	parser.add_argument("--runtime-id", default="local_ppn_emulated_probe")
	parser.add_argument("--quantization-id", default="unknown")
	parser.add_argument("--tokenizer-sha256", default="")
	parser.add_argument("--tokenizer-id", default="deepseek-v4-flash-tokenizer")
	parser.add_argument("--tokenizer-hash-status", default="not_available")
	parser.add_argument("--input-tokens", default="fixture:local-ppn-smoke")
	parser.add_argument("--comparison-kind", choices=sorted(parity.COMPARISON_KINDS), default="hidden_state")
	parser.add_argument("--parity-scope", choices=sorted(parity.PARITY_SCOPES), default="local_ppn_emulated")
	parser.add_argument("--parity-status", choices=("auto", "not_run", "passed", "failed"), default="auto")
	parser.add_argument("--quality-parity-eligible", action="store_true")
	parser.add_argument("--optimized-kernel-flag", action="append", default=[], help="Record optimized kernel flag as KEY=VALUE.")
	parser.add_argument("--pp1-output-sha256", default="")
	parser.add_argument("--ppn-output-sha256", default="")
	parser.add_argument("--tolerance-max-abs-error", type=float, default=None)
	parser.add_argument("--tolerance-mean-abs-error", type=float, default=None)
	parser.add_argument("--max-abs-error", type=float, default=None)
	parser.add_argument("--mean-abs-error", type=float, default=None)
	parser.add_argument("--token-match-count", type=int, default=None)
	parser.add_argument("--token-total-count", type=int, default=None)
	parser.add_argument("--quality-parity-detail", default="")
	parser.add_argument("--blocker-detail", default="")
	args = parser.parse_args()
	flags = {}
	for item in args.optimized_kernel_flag:
		if "=" not in item:
			parser.error("--optimized-kernel-flag must be KEY=VALUE")
		k, v = item.split("=", 1)
		flags[k] = v
	args.optimized_kernel_flags = flags
	try:
		artifact = build_artifact(args)
	except ValueError as exc:
		print(str(exc))
		return 1
	errors = parity.validate_artifact(artifact)
	if errors:
		for item in errors:
			print(item)
		return 1
	text = json.dumps(artifact, indent=2, sort_keys=True) + "\n"
	if args.out:
		Path(args.out).write_text(text, encoding="utf-8")
	else:
		print(text, end="")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
