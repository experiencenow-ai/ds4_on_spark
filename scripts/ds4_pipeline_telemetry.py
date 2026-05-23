#!/usr/bin/env python3
"""Build and validate spark-layer-pipeline-run-v1 telemetry."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

try:
	from scripts import validate_ds4_pipeline_parity as parity_validator
	from scripts._lib.json_utils import load_json
except ImportError:
	import validate_ds4_pipeline_parity as parity_validator
	from _lib.json_utils import load_json


FORMAT = "spark-layer-pipeline-run-v1"
STAGE_FORMAT = "ds4-pipeline-stage-result-v1"
MANIFEST_FORMAT = "ds4-pipeline-run-manifest-v1"
SCHEMA_VERSION = 1
QUALITY = {"not_run", "passed", "failed"}
FIXED_SPARK_COUNT_FIELDS = {"world_size", "spark_count", "num_sparks"}
REQUIRED = (
	"format",
	"artifact_schema_version",
	"artifact_sha256",
	"run_id",
	"provider_id",
	"pipeline_id",
	"model_id",
	"runtime_id",
	"manifest_sha256",
	"command_sha256",
	"input_payload_sha256",
	"output_payload_checksum",
	"sequential_result_sha256",
	"stage_results_sha256",
	"stage_count",
	"stage_nodes",
	"stage_inventory",
	"payload_bytes",
	"items",
	"sequential_items_per_s",
	"pipeline_items_per_s",
	"speedup_over_sequential",
	"bubble_overhead_ratio",
	"transfer_or_payload_GBps",
	"slowest_stage_id",
	"stage_balance_ratio",
	"quality_parity_status",
	"quality_parity_detail",
	"quality_parity_artifact",
	"quality_parity_artifact_sha256",
)


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_zero_bytes(size: int) -> str:
	h = hashlib.sha256()
	chunk = b"\x00" * 65536
	remaining = max(0, size)
	while remaining > 0:
		n = min(remaining, len(chunk))
		h.update(chunk[:n])
		remaining -= n
	return "sha256:" + h.hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	return sha256_obj(tmp)


def as_float(obj: dict[str, Any], key: str, default: float = 0.0) -> float:
	value = obj.get(key, default)
	if value is None:
		return default
	return float(value)


def as_int(obj: dict[str, Any], key: str, default: int = 0) -> int:
	value = obj.get(key, default)
	if value is None:
		return default
	return int(value)


def is_sha256_text(value: Any, allow_empty: bool = False) -> bool:
	if allow_empty and value == "":
		return True
	if not isinstance(value, str):
		return False
	return value.startswith("sha256:") and len(value) == 71


def load_parity_artifact(path_text: str, base_dir: Path | None, errors: list[str]) -> dict[str, Any] | None:
	path = Path(path_text)
	if not path.is_absolute() and base_dir is not None:
		path = base_dir / path
	try:
		return parity_validator.load_json(path)
	except (OSError, ValueError, json.JSONDecodeError) as exc:
		errors.append(f"quality_parity_artifact could not be loaded: {exc}")
		return None


def validate_parity_reference(obj: dict[str, Any], base_dir: Path | None, errors: list[str]) -> None:
	status = obj.get("quality_parity_status")
	artifact_ref = obj.get("quality_parity_artifact", "")
	artifact_hash = obj.get("quality_parity_artifact_sha256", "")
	artifact_hash_text = artifact_hash if isinstance(artifact_hash, str) else ""
	if not isinstance(artifact_ref, str):
		errors.append("quality_parity_artifact must be a string")
		return
	if not is_sha256_text(artifact_hash, allow_empty=True):
		errors.append("quality_parity_artifact_sha256 must be empty or sha256:<hex>")
	if status == "passed" and artifact_ref.strip() == "":
		errors.append("quality_parity_status passed requires quality_parity_artifact")
		return
	if status == "passed" and artifact_hash_text.strip() == "":
		errors.append("quality_parity_status passed requires quality_parity_artifact_sha256")
	if status != "passed" and artifact_ref.strip() == "":
		return
	artifact = load_parity_artifact(artifact_ref, base_dir, errors)
	if artifact is None:
		return
	artifact_errors = parity_validator.validate_artifact(artifact)
	for item in artifact_errors:
		errors.append(f"quality_parity_artifact: {item}")
	actual_hash = artifact.get("artifact_sha256")
	if artifact_hash_text != "" and artifact_hash_text != actual_hash:
		errors.append("quality_parity_artifact_sha256 does not match referenced artifact")
	if status == "passed" and not parity_validator.is_quality_parity_pass(artifact):
		errors.append("quality_parity_status passed requires a non-synthetic DS4 quality parity artifact")
	if status == "failed" and artifact.get("parity_status") == "passed":
		errors.append("quality_parity_status failed cannot reference a passed parity artifact")


def validate_run(obj: dict[str, Any], base_dir: Path | None = None) -> list[str]:
	errors: list[str] = []
	for key in REQUIRED:
		if key not in obj:
			errors.append(f"missing required field: {key}")
	for key in FIXED_SPARK_COUNT_FIELDS:
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	for key in ("run_id", "provider_id", "pipeline_id", "model_id", "runtime_id"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	if obj.get("artifact_schema_version") != SCHEMA_VERSION:
		errors.append(f"artifact_schema_version must be {SCHEMA_VERSION}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	stage_nodes = obj.get("stage_nodes")
	if not isinstance(stage_nodes, list) or len(stage_nodes) == 0:
		errors.append("stage_nodes must be a non-empty list")
	elif int(obj.get("stage_count", -1)) != len(stage_nodes):
		errors.append("stage_count must equal len(stage_nodes)")
	stage_inventory = obj.get("stage_inventory")
	if not isinstance(stage_inventory, list) or len(stage_inventory) != int(obj.get("stage_count", -1)):
		errors.append("stage_inventory must contain one entry per stage")
	q = obj.get("quality_parity_status")
	if q not in QUALITY:
		errors.append("quality_parity_status must be not_run, passed, or failed")
	if q in ("passed", "failed") and (not isinstance(obj.get("quality_parity_detail"), str) or obj.get("quality_parity_detail", "").strip() == ""):
		errors.append("quality_parity_detail must explain passed/failed parity status")
	if as_float(obj, "sequential_items_per_s") <= 0.0:
		errors.append("sequential_items_per_s must be > 0 for throughput claims")
	if as_float(obj, "pipeline_items_per_s") <= 0.0:
		errors.append("pipeline_items_per_s must be > 0 for throughput claims")
	if as_float(obj, "speedup_over_sequential") <= 0.0:
		errors.append("speedup_over_sequential must be > 0")
	if as_float(obj, "bubble_overhead_ratio") < 0.0:
		errors.append("bubble_overhead_ratio must be >= 0")
	if as_float(obj, "stage_balance_ratio") <= 0.0:
		errors.append("stage_balance_ratio must be > 0")
	if obj.get("quality_parity_detail") is None:
		errors.append("quality_parity_detail must not be null")
	for key in ("manifest_sha256", "command_sha256", "input_payload_sha256", "sequential_result_sha256", "stage_results_sha256"):
		value = obj.get(key)
		if not isinstance(value, str) or not value.startswith("sha256:"):
			errors.append(f"{key} must be a sha256: string")
	if not isinstance(obj.get("output_payload_checksum"), str) or obj.get("output_payload_checksum") == "":
		errors.append("output_payload_checksum must be a non-empty string")
	validate_parity_reference(obj, base_dir, errors)
	return errors


def stage_interval_us(stage: dict[str, Any]) -> float:
	items = max(1, as_int(stage, "items"))
	active_us = as_float(stage, "active_us")
	return active_us / float(items)


def normalize_stage(stage: dict[str, Any], fallback_node: str) -> dict[str, Any]:
	out = dict(stage)
	if "node" not in out:
		out["node"] = out.get("stage_node") or fallback_node
	return out


def build_run(
	manifest: dict[str, Any],
	sequential: dict[str, Any],
	stages: list[dict[str, Any]],
	quality_status: str,
	quality_detail: str,
	quality_parity_artifact: str = "",
	quality_parity_artifact_sha256: str = "",
) -> dict[str, Any]:
	if manifest.get("format") != MANIFEST_FORMAT:
		raise ValueError(f"manifest format must be {MANIFEST_FORMAT}")
	if sequential.get("format") not in (STAGE_FORMAT, None):
		raise ValueError("sequential result has unexpected format")
	if len(stages) == 0:
		raise ValueError("at least one stage result is required")
	stage_nodes = [str(item) for item in manifest.get("stage_nodes", [])]
	if len(stage_nodes) != len(stages):
		raise ValueError("stage_nodes count must match stage results")
	norm = [normalize_stage(stage, stage_nodes[i]) for i, stage in enumerate(stages)]
	norm = sorted(norm, key=lambda row: as_int(row, "rank"))
	sink = norm[-1]
	seq_tps = as_float(sequential, "items_per_s")
	pipe_tps = as_float(sink, "items_per_s")
	intervals = [stage_interval_us(stage) for stage in norm]
	mean_interval = sum(intervals) / float(len(intervals))
	slowest_idx = max(range(len(norm)), key=lambda i: intervals[i])
	pipeline_wall_us = max(as_float(stage, "elapsed_us") for stage in norm)
	sequential_active_us = as_float(sequential, "active_us")
	ideal_wall_us = max(intervals) * float(max(1, as_int(sink, "items")))
	bubble = max(0.0, pipeline_wall_us - ideal_wall_us) / pipeline_wall_us if pipeline_wall_us > 0.0 else 0.0
	payload_bytes = as_int(sink, "payload_bytes")
	stage_inventory = [
		{
			"stage_id": i,
			"node_id": str(norm[i].get("node") or stage_nodes[i]),
			"rank": as_int(norm[i], "rank"),
		}
		for i in range(len(norm))
	]
	run = {
		"format": FORMAT,
		"artifact_schema_version": SCHEMA_VERSION,
		"run_id": str(manifest.get("run_id", "")),
		"provider_id": str(manifest.get("provider_id", "")),
		"pipeline_id": str(manifest.get("pipeline_id", "")),
		"model_id": str(manifest.get("model_id", "")),
		"runtime_id": str(manifest.get("runtime_id", "")),
		"manifest_sha256": sha256_obj(manifest),
		"command_sha256": sha256_obj(manifest.get("command", {})),
		"input_payload_sha256": str(manifest.get("input_payload_sha256") or sha256_zero_bytes(payload_bytes)),
		"output_payload_checksum": str(sink.get("payload_checksum", "")),
		"sequential_result_sha256": sha256_obj(sequential),
		"stage_results_sha256": sha256_obj(norm),
		"stage_count": len(norm),
		"stage_nodes": stage_nodes,
		"stage_inventory": stage_inventory,
		"payload_bytes": payload_bytes,
		"items": as_int(sink, "items"),
		"microbatches": as_int(sink, "items"),
		"sequential_items_per_s": seq_tps,
		"pipeline_items_per_s": pipe_tps,
		"speedup_over_sequential": pipe_tps / seq_tps if seq_tps > 0.0 else 0.0,
		"bubble_overhead_ratio": bubble,
		"transfer_or_payload_GBps": as_float(sink, "payload_GBps"),
		"slowest_stage_id": norm[slowest_idx].get("node", slowest_idx),
		"stage_balance_ratio": max(intervals) / mean_interval if mean_interval > 0.0 else 0.0,
		"timing_summary_us": {
			"pipeline_wall_us": pipeline_wall_us,
			"sequential_active_us": sequential_active_us,
			"slowest_stage_interval_us": intervals[slowest_idx],
		},
		"quality_parity_status": quality_status,
		"quality_parity_detail": quality_detail,
		"quality_parity_artifact": quality_parity_artifact,
		"quality_parity_artifact_sha256": quality_parity_artifact_sha256,
		"stage_results": norm,
	}
	run["artifact_sha256"] = artifact_sha256(run)
	return run


def cmd_combine(args: argparse.Namespace) -> int:
	manifest = load_json(Path(args.manifest))
	sequential = load_json(Path(args.sequential))
	stages = [load_json(Path(path)) for path in args.stage]
	quality_parity_artifact_sha256 = args.quality_parity_artifact_sha256
	if args.quality_parity_artifact and quality_parity_artifact_sha256 == "":
		quality_parity_artifact_sha256 = str(load_json(Path(args.quality_parity_artifact)).get("artifact_sha256", ""))
	run = build_run(
		manifest,
		sequential,
		stages,
		args.quality_parity_status,
		args.quality_parity_detail,
		args.quality_parity_artifact,
		quality_parity_artifact_sha256,
	)
	base_dir = Path(args.out).parent if args.out else None
	errors = validate_run(run, base_dir)
	if errors:
		for item in errors:
			print(item)
		return 1
	text = json.dumps(run, indent=2, sort_keys=True) + "\n"
	if args.out:
		Path(args.out).write_text(text, encoding="utf-8")
	else:
		print(text, end="")
	return 0


def cmd_validate(args: argparse.Namespace) -> int:
	ok = True
	for path_text in args.artifact:
		path = Path(path_text)
		obj = load_json(path)
		if obj.get("format") in (STAGE_FORMAT, MANIFEST_FORMAT):
			if not args.quiet:
				print(f"skip: {path}")
			continue
		errors = validate_run(obj, path.parent)
		if errors:
			ok = False
			for item in errors:
				print(f"{path}: {item}")
		elif not args.quiet:
			print(f"ok: {path}")
	return 0 if ok else 1


def main() -> int:
	parser = argparse.ArgumentParser(description="Build or validate spark-layer-pipeline-run-v1 telemetry.")
	sub = parser.add_subparsers(dest="cmd", required=True)
	combine = sub.add_parser("combine")
	combine.add_argument("--manifest", required=True)
	combine.add_argument("--sequential", required=True)
	combine.add_argument("--stage", action="append", required=True)
	combine.add_argument("--quality-parity-status", default="not_run", choices=sorted(QUALITY))
	combine.add_argument("--quality-parity-detail", default="PP=1 vs PP=N logits/token parity not run")
	combine.add_argument("--quality-parity-artifact", default="")
	combine.add_argument("--quality-parity-artifact-sha256", default="")
	combine.add_argument("--out", default="")
	validate = sub.add_parser("validate")
	validate.add_argument("artifact", nargs="+")
	validate.add_argument("--quiet", action="store_true")
	args = parser.parse_args()
	if args.cmd == "combine":
		return cmd_combine(args)
	return cmd_validate(args)


if __name__ == "__main__":
	raise SystemExit(main())
