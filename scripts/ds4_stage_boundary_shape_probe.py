#!/usr/bin/env python3
"""Emit and validate ds4-stage-boundary-shape-v1 artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

try:
	from scripts._lib.json_utils import load_json
except ImportError:
	from _lib.json_utils import load_json


FORMAT = "ds4-stage-boundary-shape-v1"
SCHEMA_VERSION = 1
PROBE_STATUS = {"not_available", "observed", "failed"}
FIXED_SPARK_COUNT_FIELDS = {"world_size", "spark_count", "num_sparks"}
REQUIRED = (
	"format",
	"artifact_schema_version",
	"artifact_sha256",
	"model_id",
	"runtime_id",
	"quantization_id",
	"layer_count",
	"hc_mult",
	"hyper_connection_status",
	"candidate_boundary_after_layer",
	"stage_count",
	"stage_inventory",
	"layer_ranges",
	"boundary_after_layers",
	"observed_tensor_shape",
	"dtype",
	"layout",
	"probe_status",
	"probe_kind",
	"blocker_detail",
	"command_sha256",
	"artifact_refs",
)


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	return sha256_obj(tmp)


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_sha256_text(value: Any) -> bool:
	return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71


def parse_stage(text: str) -> dict[str, Any]:
	parts = text.split(":")
	if len(parts) != 4:
		raise argparse.ArgumentTypeError("stage must be stage_id:node_id:start_layer:end_layer")
	stage_id = int(parts[0])
	start = int(parts[2])
	end = int(parts[3])
	if stage_id < 0 or start < 0 or end < start:
		raise argparse.ArgumentTypeError("stage ids and layer ranges must be non-negative and ordered")
	return {"stage_id": stage_id, "node_id": parts[1], "start": start, "end": end}


def default_stages(layer_count: int) -> list[dict[str, Any]]:
	return [{"stage_id": 0, "node_id": "local", "start": 0, "end": max(0, layer_count - 1)}]


def load_config(path_text: str) -> dict[str, Any]:
	if path_text == "":
		return {}
	return load_json(Path(path_text))


def source_boundary_observation(model_path: Path, config: dict[str, Any]) -> tuple[str, Any, str, str]:
	try:
		source = model_path.read_text(encoding="utf-8")
	except OSError as exc:
		return "failed", "unknown", "unknown", f"could not read model source: {exc}"
	required = ("h = self.embed(input_ids)", "h = h.unsqueeze(2).repeat", "for layer in self.layers:", "h = layer(h, start_pos, input_ids)")
	missing = [item for item in required if item not in source]
	if missing:
		return "failed", "unknown", "unknown", "model source does not expose expected split-forward landmarks: " + ", ".join(missing)
	hc_mult = int(config.get("hc_mult", 0) or 0)
	dim = int(config.get("hidden_size", config.get("dim", 0)) or 0)
	if hc_mult <= 0 or dim <= 0:
		return "failed", "unknown", "unknown", "config does not expose positive hc_mult and hidden_size/dim"
	dtype = str(config.get("torch_dtype", "runtime_default_dtype"))
	shape = ["batch", "sequence", hc_mult, dim]
	layout = "batch,sequence,hc_mult,hidden_size after each Transformer block"
	return "observed", shape, dtype, layout


def stage_inventory(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [{"stage_id": item["stage_id"], "node_id": item["node_id"]} for item in stages]


def layer_ranges(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [{"stage_id": item["stage_id"], "start": item["start"], "end": item["end"]} for item in stages]


def boundary_after_layers(stages: list[dict[str, Any]]) -> list[int]:
	return [item["end"] for item in stages[:-1]]


def build_artifact(args: argparse.Namespace) -> dict[str, Any]:
	config = load_config(args.config)
	layer_count = int(args.layer_count or config.get("num_hidden_layers", config.get("n_layers", 43)))
	hc_mult = int(args.hc_mult or config.get("hc_mult", 4))
	stages = sorted(args.stage or default_stages(layer_count), key=lambda item: item["stage_id"])
	boundaries = boundary_after_layers(stages)
	candidate = args.candidate_boundary_after_layer
	if candidate < 0 and boundaries:
		candidate = boundaries[0]
	shape: Any = args.observed_tensor_shape
	dtype = args.dtype
	layout = args.layout
	probe_status = args.probe_status
	blocker_detail = args.blocker_detail
	if args.probe_kind == "source_static":
		probe_status, shape, dtype, layout = source_boundary_observation(Path(args.source_model_path), config)
		if probe_status != "observed" and blocker_detail == "":
			blocker_detail = str(layout)
			layout = "unknown"
		elif probe_status == "observed":
			blocker_detail = ""
	elif probe_status in ("not_available", "failed") and blocker_detail == "":
		blocker_detail = "live DS4 runtime boundary hook was not provided; run source_static or a future runtime probe to observe the boundary"
	command = {
		"probe_kind": args.probe_kind,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"layer_count": layer_count,
		"hc_mult": hc_mult,
		"candidate_boundary_after_layer": candidate,
		"stage_inventory": stage_inventory(stages),
		"layer_ranges": layer_ranges(stages),
		"source_model_path": args.source_model_path,
		"config": args.config,
		"probe_status": probe_status,
	}
	artifact = {
		"format": FORMAT,
		"artifact_schema_version": SCHEMA_VERSION,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"layer_count": layer_count,
		"hc_mult": hc_mult,
		"hyper_connection_status": "known_hc_mult" if hc_mult > 0 else "unknown",
		"candidate_boundary_after_layer": candidate,
		"stage_count": len(stages),
		"stage_inventory": stage_inventory(stages),
		"layer_ranges": layer_ranges(stages),
		"boundary_after_layers": boundaries,
		"observed_tensor_shape": shape,
		"dtype": dtype,
		"layout": layout,
		"probe_status": probe_status,
		"probe_kind": args.probe_kind,
		"blocker_detail": blocker_detail,
		"command_sha256": sha256_obj(command),
		"artifact_refs": [],
	}
	artifact["artifact_sha256"] = artifact_sha256(artifact)
	return artifact


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in REQUIRED:
		if key not in obj:
			errors.append(f"missing required field: {key}")
	for key in FIXED_SPARK_COUNT_FIELDS:
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	if obj.get("artifact_schema_version") != SCHEMA_VERSION:
		errors.append(f"artifact_schema_version must be {SCHEMA_VERSION}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	if obj.get("probe_status") not in PROBE_STATUS:
		errors.append("probe_status must be observed, failed, or not_available")
	for key in ("model_id", "runtime_id", "quantization_id", "dtype", "layout", "probe_kind"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	for key in ("layer_count", "hc_mult", "stage_count"):
		if not isinstance(obj.get(key), int) or isinstance(obj.get(key), bool) or obj.get(key) < 0:
			errors.append(f"{key} must be a non-negative integer")
	if not isinstance(obj.get("candidate_boundary_after_layer"), int):
		errors.append("candidate_boundary_after_layer must be an integer")
	if not is_sha256_text(obj.get("command_sha256")):
		errors.append("command_sha256 must be sha256:<hex>")
	stage_count = obj.get("stage_count") if isinstance(obj.get("stage_count"), int) else -1
	if not isinstance(obj.get("stage_inventory"), list) or len(obj.get("stage_inventory", [])) != stage_count:
		errors.append("stage_inventory must contain one entry per stage")
	if not isinstance(obj.get("layer_ranges"), list) or len(obj.get("layer_ranges", [])) != stage_count:
		errors.append("layer_ranges must contain one entry per stage")
	if not isinstance(obj.get("boundary_after_layers"), list):
		errors.append("boundary_after_layers must be a list")
	if obj.get("probe_status") == "observed":
		if obj.get("observed_tensor_shape") == "unknown":
			errors.append("observed probe requires observed_tensor_shape")
		if obj.get("dtype") == "unknown" or obj.get("layout") == "unknown":
			errors.append("observed probe requires dtype and layout")
	else:
		if not isinstance(obj.get("blocker_detail"), str) or obj.get("blocker_detail", "").strip() == "":
			errors.append("failed/not_available probe requires blocker_detail")
	if not isinstance(obj.get("artifact_refs"), list):
		errors.append("artifact_refs must be a list")
	return errors


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
	parser = argparse.ArgumentParser(description="Emit or validate a DS4 stage-boundary shape artifact.")
	parser.add_argument("--validate", nargs="+", help="Validate existing artifacts and exit.")
	parser.add_argument("--fix-hash", action="store_true")
	parser.add_argument("--out", default="")
	parser.add_argument("--probe-kind", choices=("none", "source_static"), default="none")
	parser.add_argument("--source-model-path", default="fixtures/model_contract/deepseek_v4_flash/inference/model.py")
	parser.add_argument("--config", default="")
	parser.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	parser.add_argument("--runtime-id", default="not_available")
	parser.add_argument("--quantization-id", default="unknown")
	parser.add_argument("--layer-count", type=int, default=0)
	parser.add_argument("--hc-mult", type=int, default=0)
	parser.add_argument("--candidate-boundary-after-layer", type=int, default=-1)
	parser.add_argument("--stage", action="append", type=parse_stage)
	parser.add_argument("--probe-status", choices=sorted(PROBE_STATUS), default="not_available")
	parser.add_argument("--dtype", default="unknown")
	parser.add_argument("--layout", default="unknown")
	parser.add_argument("--observed-tensor-shape", default="unknown")
	parser.add_argument("--blocker-detail", default="")
	args = parser.parse_args()
	if args.validate:
		return cmd_validate([Path(item) for item in args.validate], bool(args.fix_hash))
	artifact = build_artifact(args)
	errors = validate_artifact(artifact)
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
