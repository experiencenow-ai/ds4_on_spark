#!/usr/bin/env python3
"""Build and validate spark-layer-pipeline-run-v1 telemetry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FORMAT = "spark-layer-pipeline-run-v1"
STAGE_FORMAT = "ds4-pipeline-stage-result-v1"
MANIFEST_FORMAT = "ds4-pipeline-run-manifest-v1"
QUALITY = {"not_run", "passed", "failed"}
REQUIRED = (
	"format",
	"run_id",
	"pipeline_id",
	"model_id",
	"runtime_id",
	"stage_count",
	"stage_nodes",
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
)


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


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


def validate_run(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in REQUIRED:
		if key not in obj:
			errors.append(f"missing required field: {key}")
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	stage_nodes = obj.get("stage_nodes")
	if not isinstance(stage_nodes, list) or len(stage_nodes) == 0:
		errors.append("stage_nodes must be a non-empty list")
	elif int(obj.get("stage_count", -1)) != len(stage_nodes):
		errors.append("stage_count must equal len(stage_nodes)")
	q = obj.get("quality_parity_status")
	if q not in QUALITY:
		errors.append("quality_parity_status must be not_run, passed, or failed")
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
	ideal_wall_us = max(intervals) * float(max(1, as_int(sink, "items")))
	bubble = max(0.0, pipeline_wall_us - ideal_wall_us) / pipeline_wall_us if pipeline_wall_us > 0.0 else 0.0
	return {
		"format": FORMAT,
		"run_id": str(manifest.get("run_id", "")),
		"pipeline_id": str(manifest.get("pipeline_id", "")),
		"model_id": str(manifest.get("model_id", "")),
		"runtime_id": str(manifest.get("runtime_id", "")),
		"stage_count": len(norm),
		"stage_nodes": stage_nodes,
		"payload_bytes": as_int(sink, "payload_bytes"),
		"items": as_int(sink, "items"),
		"microbatches": as_int(sink, "items"),
		"sequential_items_per_s": seq_tps,
		"pipeline_items_per_s": pipe_tps,
		"speedup_over_sequential": pipe_tps / seq_tps if seq_tps > 0.0 else 0.0,
		"bubble_overhead_ratio": bubble,
		"transfer_or_payload_GBps": as_float(sink, "payload_GBps"),
		"slowest_stage_id": norm[slowest_idx].get("node", slowest_idx),
		"stage_balance_ratio": max(intervals) / mean_interval if mean_interval > 0.0 else 0.0,
		"quality_parity_status": quality_status,
		"quality_parity_detail": quality_detail,
		"stage_results": norm,
	}


def cmd_combine(args: argparse.Namespace) -> int:
	manifest = load_json(Path(args.manifest))
	sequential = load_json(Path(args.sequential))
	stages = [load_json(Path(path)) for path in args.stage]
	run = build_run(manifest, sequential, stages, args.quality_parity_status, args.quality_parity_detail)
	errors = validate_run(run)
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
		errors = validate_run(obj)
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
