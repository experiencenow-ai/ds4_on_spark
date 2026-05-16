#!/usr/bin/env python3
"""Package and compare DS4 PP=1 / PP=N final-output hashes."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

try:
	from scripts import validate_ds4_pipeline_parity as parity
except ImportError:
	import validate_ds4_pipeline_parity as parity


EXPORT_FORMAT = "ds4-final-output-export-v1"
MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"
RUNTIME_ID = "antirez-ds4-3630e64+explicit-preload+stage-handoff+tcp"
QUANT_ID = "DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf"


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_text(text: str) -> str:
	return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_file(path: Path) -> str:
	h = hashlib.sha256()
	with path.open("rb") as f:
		for chunk in iter(lambda: f.read(1048576), b""):
			h.update(chunk)
	return "sha256:" + h.hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	return sha256_obj(tmp)


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_flags(items: list[str]) -> dict[str, str]:
	flags: dict[str, str] = {}
	for item in items:
		if "=" not in item:
			raise ValueError("optimized kernel flags must be KEY=VALUE")
		k, v = item.split("=", 1)
		if k == "":
			raise ValueError("optimized kernel flag key must be non-empty")
		flags[k] = v
	return flags


def normalize_layer_ranges(raw: Any) -> list[dict[str, Any]]:
	out: list[dict[str, Any]] = []
	if not isinstance(raw, list):
		return out
	for idx, item in enumerate(raw):
		if isinstance(item, dict):
			row = dict(item)
			row.setdefault("stage_id", idx)
			out.append(row)
		elif isinstance(item, list) and len(item) == 2:
			row = {"stage_id": idx, "start": int(item[0]), "end": int(item[1])}
			out.append(row)
	return out


def output_sha_from_hash(hash_text: str) -> str:
	return sha256_text("ds4-output-hash:" + hash_text)


def build_export_from_handoff(args: argparse.Namespace) -> dict[str, Any]:
	stage = load_json(Path(args.stage_handoff))
	hashes = stage.get("final_logits_hashes")
	if isinstance(hashes, list) and hashes:
		output_hash = str(hashes[-1])
	else:
		output_hash = str(stage.get("final_logits_hash", ""))
	if output_hash == "":
		raise ValueError("stage handoff artifact has no final logits hash")
	stage_env = stage.get("stage_env") if isinstance(stage.get("stage_env"), dict) else {}
	flags = parse_flags(args.optimized_kernel_flag)
	if not flags:
		flags = {str(k): str(v) for k, v in stage_env.items() if str(k).startswith("DS4_CUDA_MOE_")}
	command = {
		"export_role": "ppn",
		"stage_handoff": args.stage_handoff,
		"comparison_kind": args.comparison_kind,
		"optimized_kernel_flags": flags,
	}
	export = {
		"format": EXPORT_FORMAT,
		"export_role": "ppn",
		"model_id": str(stage.get("model_id", MODEL_ID)),
		"runtime_id": str(stage.get("runtime_id", RUNTIME_ID)),
		"quantization_id": str(stage.get("quantization_id", QUANT_ID)),
		"comparison_kind": args.comparison_kind,
		"input_sha256": args.input_sha256 or sha256_text(args.input_text),
		"output_hash": output_hash,
		"output_sha256": output_sha_from_hash(output_hash),
		"stage_count": int(stage.get("stage_count", 0)),
		"stage_inventory": [{"stage_id": i, "node_id": n} for i, n in enumerate(stage.get("stage_nodes", []))],
		"layer_ranges": normalize_layer_ranges(stage.get("layer_ranges")),
		"boundary_state_layout": {
			"status": "observed_stage_handoff",
			"dtype": str(stage.get("boundary_dtype", "unknown")),
			"layout": str(stage.get("boundary_layout", "unknown")),
			"shape": [int(stage.get("batch_size", 0)), 4, 4096],
		},
		"boundary_after_layers": [int(r[1]) - 1 for r in stage.get("layer_ranges", [])[:-1] if isinstance(r, list) and len(r) == 2],
		"optimized_kernel_flags": flags,
		"command_sha256": sha256_obj(command),
		"source_artifact": args.stage_handoff,
		"source_artifact_sha256": sha256_file(Path(args.stage_handoff)),
	}
	export["artifact_sha256"] = artifact_sha256(export)
	return export


def build_export_from_hash(args: argparse.Namespace) -> dict[str, Any]:
	flags = parse_flags(args.optimized_kernel_flag)
	output_hash = args.output_hash or args.output_sha256
	if output_hash == "":
		raise ValueError("--output-hash or --output-sha256 is required")
	output_sha = args.output_sha256 if args.output_sha256 else output_sha_from_hash(output_hash)
	layer_ranges = normalize_layer_ranges(json.loads(args.layer_ranges))
	stage_inventory = [{"stage_id": int(row.get("stage_id", idx)), "node_id": f"local{idx}"} for idx, row in enumerate(layer_ranges)]
	command = {
		"export_role": args.export_role,
		"comparison_kind": args.comparison_kind,
		"input_sha256": args.input_sha256 or sha256_text(args.input_text),
		"output_hash": output_hash,
		"optimized_kernel_flags": flags,
	}
	export = {
		"format": EXPORT_FORMAT,
		"export_role": args.export_role,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"comparison_kind": args.comparison_kind,
		"input_sha256": args.input_sha256 or sha256_text(args.input_text),
		"output_hash": output_hash,
		"output_sha256": output_sha,
		"stage_count": args.stage_count,
		"stage_inventory": stage_inventory,
		"layer_ranges": layer_ranges,
		"boundary_state_layout": {
			"status": args.boundary_status,
			"dtype": args.boundary_dtype,
			"layout": args.boundary_layout,
			"shape": json.loads(args.boundary_shape),
		},
		"boundary_after_layers": json.loads(args.boundary_after_layers),
		"optimized_kernel_flags": flags,
		"command_sha256": sha256_obj(command),
		"source_artifact": "",
		"source_artifact_sha256": "",
	}
	export["artifact_sha256"] = artifact_sha256(export)
	return export


def validate_export(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != EXPORT_FORMAT:
		errors.append(f"format must be {EXPORT_FORMAT}")
	for key in ("export_role", "model_id", "runtime_id", "quantization_id", "comparison_kind", "input_sha256", "output_hash", "output_sha256", "command_sha256", "artifact_sha256"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical export body")
	if obj.get("comparison_kind") not in parity.QUALITY_COMPARISON_KINDS:
		errors.append("comparison_kind must be logits, tokens, or hidden_state")
	if not isinstance(obj.get("optimized_kernel_flags"), dict):
		errors.append("optimized_kernel_flags must be an object")
	return errors


def ref_for(path_text: str, obj: dict[str, Any], name: str) -> dict[str, str]:
	return {"name": name, "path": path_text, "sha256": str(obj.get("artifact_sha256", ""))}


def load_export(path_text: str, errors: list[str]) -> Optional[dict[str, Any]]:
	if path_text == "":
		return None
	try:
		obj = load_json(Path(path_text))
	except (OSError, ValueError, json.JSONDecodeError) as exc:
		errors.append(f"{path_text}: {exc}")
		return None
	for item in validate_export(obj):
		errors.append(f"{path_text}: {item}")
	return obj


def build_parity(args: argparse.Namespace) -> dict[str, Any]:
	errors: list[str] = []
	pp1 = load_export(args.pp1_export, errors)
	ppn = load_export(args.ppn_export, errors)
	if errors:
		raise ValueError("; ".join(errors))
	source = ppn or pp1
	if source is None:
		raise ValueError("at least one export is required")
	flags = dict(source.get("optimized_kernel_flags", {}))
	if pp1 is not None and ppn is not None and pp1.get("optimized_kernel_flags") != ppn.get("optimized_kernel_flags"):
		raise ValueError("PP=1 and PP=N optimized_kernel_flags must match")
	if pp1 is not None and ppn is not None and pp1.get("input_sha256") != ppn.get("input_sha256"):
		raise ValueError("PP=1 and PP=N input_sha256 must match")
	for key in ("model_id", "runtime_id", "quantization_id", "comparison_kind"):
		if pp1 is not None and ppn is not None and pp1.get(key) != ppn.get(key):
			raise ValueError(f"PP=1 and PP=N {key} must match")
	stage_count = int(source.get("stage_count", 1))
	layer_ranges = copy.deepcopy(source.get("layer_ranges", []))
	stage_inventory = copy.deepcopy(source.get("stage_inventory", []))
	boundary_layout = copy.deepcopy(source.get("boundary_state_layout", {"status": "unknown", "dtype": "unknown", "layout": "unknown", "shape": "unknown"}))
	boundary_after = copy.deepcopy(source.get("boundary_after_layers", []))
	pp1_sha = "" if pp1 is None else str(pp1.get("output_sha256", ""))
	ppn_sha = "" if ppn is None else str(ppn.get("output_sha256", ""))
	status = "not_run"
	blocker = ""
	token_match_count = None
	token_total_count = None
	max_abs_error = None
	mean_abs_error = None
	quality_detail = ""
	if pp1 is None:
		blocker = "PP=1 final-output export is missing for the same prompt/model/context."
	elif ppn is None:
		blocker = "PP=N final-output export is missing for the same prompt/model/context."
	elif pp1_sha == ppn_sha:
		status = "passed"
		token_match_count = 1
		token_total_count = 1
		max_abs_error = 0.0
		mean_abs_error = 0.0
		quality_detail = "PP=1 and PP=N final-output hashes match."
	else:
		status = "failed"
		blocker = "PP=1 and PP=N final-output hashes differ."
		token_match_count = 0
		token_total_count = 1
		max_abs_error = None
		mean_abs_error = None
	if quality_detail == "":
		quality_detail = blocker
	command = {
		"script": "compare_ds4_pp1_ppn_outputs.py",
		"pp1_export": args.pp1_export,
		"ppn_export": args.ppn_export,
		"parity_scope": args.parity_scope,
		"comparison_kind": args.comparison_kind,
	}
	artifact = {
		"format": parity.FORMAT,
		"artifact_schema_version": parity.SCHEMA_VERSION,
		"parity_run_id": args.parity_run_id,
		"parity_scope": args.parity_scope,
		"provider_id": args.provider_id,
		"pipeline_id": args.pipeline_id,
		"model_id": str(source.get("model_id", MODEL_ID)),
		"runtime_id": str(source.get("runtime_id", RUNTIME_ID)),
		"tokenizer_sha256": args.tokenizer_sha256,
		"tokenizer_id": args.tokenizer_id,
		"tokenizer_hash_status": args.tokenizer_hash_status,
		"quantization_id": str(source.get("quantization_id", QUANT_ID)),
		"stage_count": stage_count,
		"stage_manifest_sha256": sha256_obj({"stage_inventory": stage_inventory, "layer_ranges": layer_ranges, "boundary_after_layers": boundary_after}),
		"stage_inventory": stage_inventory,
		"layer_ranges": layer_ranges,
		"boundary_state_layout": boundary_layout,
		"boundary_after_layers": boundary_after,
		"input_tokens_sha256": str(source.get("input_sha256", "")),
		"pp1_output_sha256": pp1_sha,
		"ppn_output_sha256": ppn_sha,
		"comparison_kind": args.comparison_kind,
		"parity_status": status,
		"quality_parity_eligible": bool(status == "passed" and args.quality_parity_eligible),
		"optimized_kernel_flags": flags,
		"tolerance": {"max_abs_error": 0.0 if status == "passed" else None, "mean_abs_error": 0.0 if status == "passed" else None},
		"max_abs_error": max_abs_error,
		"mean_abs_error": mean_abs_error,
		"token_match_count": token_match_count,
		"token_total_count": token_total_count,
		"quality_parity_detail": quality_detail,
		"blocker_detail": "" if status == "passed" else blocker,
		"command_sha256": sha256_obj(command),
		"artifact_refs": [],
	}
	if pp1 is not None:
		artifact["artifact_refs"].append(ref_for(args.pp1_export, pp1, "pp1_final_output_export"))
	if ppn is not None:
		artifact["artifact_refs"].append(ref_for(args.ppn_export, ppn, "ppn_final_output_export"))
	artifact["artifact_sha256"] = parity.artifact_sha256(artifact)
	errors = parity.validate_artifact(artifact)
	if errors:
		raise ValueError("; ".join(errors))
	return artifact


def add_common_export_args(p: argparse.ArgumentParser) -> None:
	p.add_argument("--out", required=True)
	p.add_argument("--comparison-kind", choices=sorted(parity.QUALITY_COMPARISON_KINDS), default="logits")
	p.add_argument("--input-text", default="fixture:ds4-pp1-ppn-output")
	p.add_argument("--input-sha256", default="")
	p.add_argument("--optimized-kernel-flag", action="append", default=[])


def main(argv: Optional[list[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Compare DS4 PP=1 and PP=N final-output exports.")
	sub = parser.add_subparsers(dest="cmd", required=True)
	p_stage = sub.add_parser("export-ppn-from-stage-handoff")
	add_common_export_args(p_stage)
	p_stage.add_argument("--stage-handoff", required=True)
	p_hash = sub.add_parser("export-from-hash")
	add_common_export_args(p_hash)
	p_hash.add_argument("--export-role", choices=("pp1", "ppn"), required=True)
	p_hash.add_argument("--model-id", default=MODEL_ID)
	p_hash.add_argument("--runtime-id", default=RUNTIME_ID)
	p_hash.add_argument("--quantization-id", default=QUANT_ID)
	p_hash.add_argument("--output-hash", default="")
	p_hash.add_argument("--output-sha256", default="")
	p_hash.add_argument("--stage-count", type=int, default=1)
	p_hash.add_argument("--layer-ranges", default='[{"stage_id":0,"start":0,"end":43,"include_head":true}]')
	p_hash.add_argument("--boundary-status", default="not_observed")
	p_hash.add_argument("--boundary-dtype", default="unknown")
	p_hash.add_argument("--boundary-layout", default="unknown")
	p_hash.add_argument("--boundary-shape", default='"unknown"')
	p_hash.add_argument("--boundary-after-layers", default="[]")
	p_cmp = sub.add_parser("compare")
	p_cmp.add_argument("--pp1-export", default="")
	p_cmp.add_argument("--ppn-export", default="")
	p_cmp.add_argument("--out", required=True)
	p_cmp.add_argument("--parity-run-id", default="ds4-pp1-ppn-output-compare")
	p_cmp.add_argument("--parity-scope", choices=sorted(parity.PARITY_SCOPES), default="cross_spark_ppn")
	p_cmp.add_argument("--comparison-kind", choices=sorted(parity.QUALITY_COMPARISON_KINDS), default="logits")
	p_cmp.add_argument("--quality-parity-eligible", action="store_true")
	p_cmp.add_argument("--provider-id", default="spark-ring-dsv4-layer-pipeline")
	p_cmp.add_argument("--pipeline-id", default="spark012-ds4-layer-pipeline-output-compare")
	p_cmp.add_argument("--tokenizer-sha256", default="")
	p_cmp.add_argument("--tokenizer-id", default="deepseek-v4-flash-tokenizer")
	p_cmp.add_argument("--tokenizer-hash-status", default="not_available")
	args = parser.parse_args(argv)
	try:
		if args.cmd == "export-ppn-from-stage-handoff":
			obj = build_export_from_handoff(args)
		elif args.cmd == "export-from-hash":
			obj = build_export_from_hash(args)
			errors = validate_export(obj)
			if errors:
				raise ValueError("; ".join(errors))
		else:
			obj = build_parity(args)
	except ValueError as exc:
		print(str(exc))
		return 1
	write_json(Path(args.out), obj)
	print(json.dumps(obj, indent=2, sort_keys=True))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
