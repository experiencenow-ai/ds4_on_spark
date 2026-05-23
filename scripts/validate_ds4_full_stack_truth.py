#!/usr/bin/env python3
"""Validate and build ds4-full-stack-truth-v1 records."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

try:
	from scripts._lib.json_utils import artifact_sha256
	from scripts._lib.json_utils import is_sha256_text
	from scripts._lib.source_probe import tail_text
except ImportError:
	from _lib.json_utils import artifact_sha256
	from _lib.json_utils import is_sha256_text
	from _lib.source_probe import tail_text


FORMAT = "ds4-full-stack-truth-v1"
SCHEMA_VERSION = 1
BASELINE_TOK_S = 13.3
PATH_KINDS = {
	"output_head",
	"decode_stack",
	"batch_stack",
	"batch_stack_no_head",
	"batch_stack_with_head",
}
FAILURE_STATUS = {"success", "failed", "not_run"}
BLOCKER_KINDS = {
	"none",
	"startup_preload_timeout",
	"lazy_moe_range_upload",
	"q8_0_lazy_range_upload",
	"full_slab_fallback",
	"expert_slice_cache_miss",
	"cuda_context_poisoning_after_timeout",
	"insufficient_memory",
	"command_runtime_bug",
	"unknown",
}
FIXED_SPARK_COUNT_FIELDS = {"world_size", "spark_count", "num_sparks"}
CEILING_DEFAULTS = {
	"synthetic_layer_ceiling": 409.0,
	"ffn_envelope_ceiling": 558.0,
	"moe_only_ceiling": 620.0,
}
REQUIRED = (
	"format",
	"artifact_schema_version",
	"artifact_sha256",
	"run_id",
	"model_id",
	"runtime_id",
	"quantization_id",
	"spark_node",
	"batch_size",
	"path_kind",
	"layers_executed",
	"includes_output_head",
	"includes_attention",
	"includes_kv",
	"includes_sampling",
	"warmup_policy",
	"residency_policy",
	"best_ms",
	"avg_ms",
	"tokens_per_second",
	"finite_output",
	"output_hash",
	"failure_status",
	"blocker_kind",
	"blocker_detail",
	"compared_ceiling_tok_s",
	"realization_ratio",
	"artifact_refs",
)


class FullStackTruthError(ValueError):
	pass


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise FullStackTruthError(f"{path}: root must be an object")
	return obj


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_number(value: Any) -> bool:
	return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def json_line_from_text(text: str) -> dict[str, Any] | None:
	for line in text.splitlines():
		line = line.strip()
		if not line.startswith("{") or not line.endswith("}"):
			continue
		try:
			obj = json.loads(line)
		except json.JSONDecodeError:
			continue
		if isinstance(obj, dict):
			return obj
	return None


def float_from_probe(probe: dict[str, Any], *keys: str) -> float | None:
	for key in keys:
		value = probe.get(key)
		if is_number(value):
			return float(value)
	return None


def output_hash_from_probe(probe: dict[str, Any]) -> str:
	for key in ("output_hash", "logits_sha256", "out_sha256", "tokens_sha256"):
		value = probe.get(key)
		if is_sha256_text(value):
			return str(value)
	for key in ("logits_fnv64", "out_fnv64", "hc_fnv64", "output_fnv64", "tokens_fnv64"):
		value = probe.get(key)
		if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{16}", value):
			return "fnv64:" + value.lower()
	return ""


def finite_output_from_probe(probe: dict[str, Any], rc: int) -> bool:
	for key in ("logits_nonfinite", "out_nonfinite", "hc_nonfinite", "output_nonfinite"):
		value = probe.get(key)
		if is_number(value):
			return int(value) == 0
	if rc != 0:
		return False
	return output_hash_from_probe(probe) != ""


def classify_blocker(text: str, rc: int) -> str:
	low = text.lower()
	if rc == 0:
		return "none"
	if "out of memory" in low or "cuda_error_out_of_memory" in low or "cudamalloc" in low and "failed" in low:
		return "insufficient_memory"
	if "illegal memory" in low or "context is destroyed" in low or "context poison" in low or "context poisoned" in low:
		return "cuda_context_poisoning_after_timeout"
	if "startup" in low and "preload" in low and ("timeout" in low or "timed out" in low):
		return "startup_preload_timeout"
	if "accelerator stopped startup model cache" in low:
		return "startup_preload_timeout"
	if ("q8_0" in low or "attn_out_a" in low) and ("lazy" in low or "range" in low or "upload" in low or "timeout" in low):
		return "q8_0_lazy_range_upload"
	if "full-slab" in low or "full slab" in low or "whole-slab" in low or "fallback" in low and "expert" in low:
		return "full_slab_fallback"
	if ("moe_down_expert_batched" in low or "moe" in low) and ("lazy" in low or "range" in low or "upload" in low or "timeout" in low):
		return "lazy_moe_range_upload"
	if "expert slice" in low and ("miss" in low or "uncached" in low or "cache" in low):
		return "expert_slice_cache_miss"
	if "command not found" in low or "unknown option" in low or "no such file" in low or "not found" in low and "./ds4" in low:
		return "command_runtime_bug"
	return "unknown"


def ratios(tokens_per_second: float | None, ceilings: dict[str, float]) -> dict[str, float | None]:
	out: dict[str, float | None] = {}
	for key, ceiling in ceilings.items():
		out["vs_" + key] = (float(tokens_per_second) / float(ceiling)) if tokens_per_second is not None and ceiling > 0.0 else None
	return out


def build_record(args: argparse.Namespace) -> dict[str, Any]:
	stdout = Path(args.stdout).read_text(encoding="utf-8", errors="replace") if args.stdout else ""
	stderr = Path(args.stderr).read_text(encoding="utf-8", errors="replace") if args.stderr else ""
	rc = int(args.rc)
	probe = json_line_from_text(stdout) or json_line_from_text(stderr) or {}
	best_ms = float_from_probe(probe, "best_ms")
	avg_ms = float_from_probe(probe, "avg_ms")
	tps = float_from_probe(probe, "tokens_per_second", "tok_s", "best_tokens_per_s", "best_rows_per_s", "best_heads_per_s")
	if tps is None and best_ms is not None and best_ms > 0.0 and args.path_kind == "output_head":
		tps = 1000.0 / best_ms
	output_hash = output_hash_from_probe(probe)
	finite_output = finite_output_from_probe(probe, rc)
	failure_status = "success" if rc == 0 and finite_output and output_hash != "" else "failed"
	blocker_text = "\n".join([stderr, stdout])
	blocker_kind = classify_blocker(blocker_text, rc)
	blocker_detail = "" if blocker_kind == "none" else tail_text(blocker_text)
	ceilings = dict(CEILING_DEFAULTS)
	record = {
		"format": FORMAT,
		"artifact_schema_version": SCHEMA_VERSION,
		"artifact_sha256": "",
		"run_id": args.run_id,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"spark_node": args.spark_node,
		"batch_size": int(args.batch_size),
		"path_kind": args.path_kind,
		"layers_executed": int(args.layers_executed),
		"includes_output_head": bool(args.includes_output_head),
		"includes_attention": bool(args.includes_attention),
		"includes_kv": bool(args.includes_kv),
		"includes_sampling": bool(args.includes_sampling),
		"warmup_policy": args.warmup_policy,
		"residency_policy": args.residency_policy,
		"best_ms": best_ms,
		"avg_ms": avg_ms,
		"tokens_per_second": tps,
		"finite_output": finite_output,
		"output_hash": output_hash,
		"failure_status": failure_status,
		"blocker_kind": blocker_kind,
		"blocker_detail": blocker_detail,
		"compared_ceiling_tok_s": ceilings,
		"realization_ratio": ratios(tps, ceilings),
		"artifact_refs": {
			"stdout": args.stdout or "",
			"stderr": args.stderr or "",
		},
	}
	record["artifact_sha256"] = artifact_sha256(record)
	return record


def validate_record(obj: dict[str, Any]) -> list[str]:
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
	for key in ("run_id", "model_id", "runtime_id", "quantization_id", "spark_node", "warmup_policy", "residency_policy"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	if obj.get("path_kind") not in PATH_KINDS:
		errors.append("path_kind must be one of the declared full-stack truth paths")
	if obj.get("failure_status") not in FAILURE_STATUS:
		errors.append("failure_status must be success, failed, or not_run")
	if obj.get("blocker_kind") not in BLOCKER_KINDS:
		errors.append("blocker_kind must be one of the declared residency blockers")
	for key in ("batch_size", "layers_executed"):
		if not isinstance(obj.get(key), int) or isinstance(obj.get(key), bool) or int(obj.get(key, -1)) < 0:
			errors.append(f"{key} must be a non-negative integer")
	for key in ("includes_output_head", "includes_attention", "includes_kv", "includes_sampling", "finite_output"):
		if not isinstance(obj.get(key), bool):
			errors.append(f"{key} must be boolean")
	path_kind = str(obj.get("path_kind", ""))
	if path_kind.startswith("batch") and int(obj.get("batch_size", 0)) <= 0:
		errors.append("batch throughput claim requires batch_size > 0")
	if path_kind in ("decode_stack", "batch_stack", "batch_stack_with_head") and obj.get("failure_status") == "success" and int(obj.get("layers_executed", 0)) < 43:
		errors.append("full-stack success requires layers_executed >= 43")
	if obj.get("failure_status") == "success":
		if obj.get("finite_output") is not True:
			errors.append("success requires finite_output=true")
		if not isinstance(obj.get("output_hash"), str) or obj.get("output_hash", "").strip() == "":
			errors.append("success requires output_hash")
		if not is_number(obj.get("tokens_per_second")) or float(obj.get("tokens_per_second", 0.0)) <= 0.0:
			errors.append("success requires tokens_per_second > 0")
		if obj.get("blocker_kind") != "none":
			errors.append("success requires blocker_kind=none")
	else:
		if obj.get("blocker_kind") == "none":
			errors.append("failed/not_run records require a non-none blocker_kind")
		if not isinstance(obj.get("blocker_detail"), str) or obj.get("blocker_detail", "").strip() == "":
			errors.append("failed/not_run records require blocker_detail")
	tps = obj.get("tokens_per_second")
	if tps is not None:
		if not is_number(tps):
			errors.append("tokens_per_second must be numeric or null")
		elif float(tps) > 15.0:
			for key in ("path_kind", "includes_output_head", "includes_attention", "includes_kv", "includes_sampling", "layers_executed"):
				if key not in obj:
					errors.append(">15 tok/s claim requires explicit path_kind and included components")
	ceilings = obj.get("compared_ceiling_tok_s")
	rr = obj.get("realization_ratio")
	if not isinstance(ceilings, dict):
		errors.append("compared_ceiling_tok_s must be an object")
		ceilings = {}
	if not isinstance(rr, dict):
		errors.append("realization_ratio must be an object")
		rr = {}
	for key in ("synthetic_layer_ceiling", "ffn_envelope_ceiling", "moe_only_ceiling"):
		if not is_number(ceilings.get(key)):
			errors.append(f"compared_ceiling_tok_s.{key} must be numeric")
		if "vs_" + key not in rr:
			errors.append(f"realization_ratio.vs_{key} is required")
		elif rr.get("vs_" + key) is not None and not is_number(rr.get("vs_" + key)):
			errors.append(f"realization_ratio.vs_{key} must be numeric or null")
	refs = obj.get("artifact_refs")
	if not isinstance(refs, dict):
		errors.append("artifact_refs must be an object")
	return errors


def cmd_validate(paths: list[Path], fix_hash: bool) -> int:
	ok = True
	for path in paths:
		obj = load_json(path)
		if fix_hash:
			obj["artifact_sha256"] = artifact_sha256(obj)
			write_json(path, obj)
		errors = validate_record(obj)
		if errors:
			ok = False
			for item in errors:
				print(f"{path}: {item}")
		else:
			print(f"ok: {path}")
	return 0 if ok else 1


def cmd_record(args: argparse.Namespace) -> int:
	record = build_record(args)
	errors = validate_record(record)
	if errors:
		for item in errors:
			print(f"record: {item}")
		return 1
	write_json(Path(args.out), record)
	print(f"wrote: {args.out}")
	return 0


def add_record_args(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("--out", required=True)
	parser.add_argument("--run-id", required=True)
	parser.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	parser.add_argument("--runtime-id", default="antirez-ds4-cuda-stack-probe")
	parser.add_argument("--quantization-id", default="DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf")
	parser.add_argument("--spark-node", required=True)
	parser.add_argument("--batch-size", type=int, required=True)
	parser.add_argument("--path-kind", choices=sorted(PATH_KINDS), required=True)
	parser.add_argument("--layers-executed", type=int, required=True)
	parser.add_argument("--includes-output-head", action="store_true")
	parser.add_argument("--includes-attention", action="store_true")
	parser.add_argument("--includes-kv", action="store_true")
	parser.add_argument("--includes-sampling", action="store_true")
	parser.add_argument("--warmup-policy", default="single-run")
	parser.add_argument("--residency-policy", default="skip-startup-cache-with-expert-slice-cache")
	parser.add_argument("--stdout", default="")
	parser.add_argument("--stderr", default="")
	parser.add_argument("--rc", type=int, required=True)


def main() -> int:
	if len(sys.argv) > 1 and sys.argv[1] not in ("record", "validate", "-h", "--help"):
		return cmd_validate([Path(item) for item in sys.argv[1:]], False)
	parser = argparse.ArgumentParser(description="Validate or build ds4-full-stack-truth-v1 records.")
	sub = parser.add_subparsers(dest="cmd")
	record = sub.add_parser("record", help="Build a truth record from probe logs.")
	add_record_args(record)
	record.set_defaults(func=cmd_record)
	validate = sub.add_parser("validate", help="Validate truth records.")
	validate.add_argument("artifacts", nargs="+")
	validate.add_argument("--fix-hash", action="store_true")
	args = parser.parse_args()
	if args.cmd == "record":
		return args.func(args)
	if args.cmd == "validate":
		return cmd_validate([Path(item) for item in args.artifacts], bool(args.fix_hash))
	parser.print_help()
	return 2


if __name__ == "__main__":
	raise SystemExit(main())
