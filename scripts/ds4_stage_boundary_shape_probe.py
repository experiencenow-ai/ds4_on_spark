#!/usr/bin/env python3
"""Emit a DS4 stage-boundary shape probe scaffold artifact."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from typing import Any


FORMAT = "ds4-stage-boundary-shape-v1"
SCHEMA_VERSION = 1


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	return sha256_obj(tmp)


def main() -> int:
	parser = argparse.ArgumentParser(description="Emit a DS4 stage-boundary shape probe artifact.")
	parser.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	parser.add_argument("--runtime-id", default="not_available")
	parser.add_argument("--quantization-id", default="unknown")
	parser.add_argument("--layer-count", type=int, default=43)
	parser.add_argument("--hc-mult", type=int, default=4)
	parser.add_argument("--candidate-boundary-after-layer", type=int, default=-1)
	parser.add_argument("--probe-status", choices=("not_available", "observed", "failed"), default="not_available")
	parser.add_argument("--dtype", default="unknown")
	parser.add_argument("--layout", default="unknown")
	parser.add_argument("--observed-tensor-shape", default="unknown")
	args = parser.parse_args()
	command = {
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"layer_count": args.layer_count,
		"hc_mult": args.hc_mult,
		"candidate_boundary_after_layer": args.candidate_boundary_after_layer,
		"probe_status": args.probe_status,
		"dtype": args.dtype,
		"layout": args.layout,
		"observed_tensor_shape": args.observed_tensor_shape,
	}
	artifact = {
		"format": FORMAT,
		"artifact_schema_version": SCHEMA_VERSION,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"layer_count": args.layer_count,
		"hc_mult": args.hc_mult,
		"hyper_connection_status": "known_hc_mult" if args.hc_mult > 0 else "unknown",
		"candidate_boundary_after_layer": args.candidate_boundary_after_layer,
		"observed_tensor_shape": args.observed_tensor_shape,
		"dtype": args.dtype,
		"layout": args.layout,
		"probe_status": args.probe_status,
		"command_sha256": sha256_obj(command),
		"artifact_refs": [],
	}
	artifact["artifact_sha256"] = artifact_sha256(artifact)
	print(json.dumps(artifact, indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
