#!/usr/bin/env python3
"""Build and validate DS4 performance-iceberg records."""

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
	from scripts._lib.source_probe import tail_text
except ImportError:
	from _lib.json_utils import artifact_sha256
	from _lib.source_probe import tail_text


RECORD_FORMAT = "ds4-perf-iceberg-record-v1"
SUMMARY_FORMAT = "ds4-perf-iceberg-summary-v1"
SCHEMA_VERSION = 1
BASELINE_TOK_S = 13.3
CEILINGS = {
	"synthetic_layer_ceiling": 409.0,
	"ffn_envelope_ceiling": 558.0,
	"moe_only_ceiling": 620.0,
}
COMPONENT_KINDS = {
	"output_head",
	"prefix_miss_prefill",
	"prefix_hit_load_or_fork",
	"suffix_prefill",
	"full_stack_decode",
	"full_stack_batch_no_head",
	"full_stack_batch_with_head",
	"residency_trace",
	"kv_pressure",
	"activation_transfer",
}
FAILURE_STATUS = {"success", "failed", "not_run"}
BLOCKER_KINDS = {
	"none",
	"startup_preload_timeout",
	"lazy_moe_range_upload",
	"q8_0_lazy_upload",
	"full_slab_fallback",
	"expert_slice_cache_miss",
	"output_head_cap",
	"prefix_prefill_cap",
	"suffix_prefill_cap",
	"kv_capacity",
	"kv_bandwidth",
	"scheduler_starvation",
	"stage_transfer_cap",
	"cuda_context_poisoned",
	"insufficient_memory",
	"command_runtime_bug",
	"not_instrumented",
	"unknown",
}
FIXED_SPARK_COUNT_FIELDS = {"world_size", "spark_count", "num_sparks"}
SUMMARY_REQUIRED = (
	"format",
	"artifact_schema_version",
	"artifact_sha256",
	"run_id",
	"model_id",
	"runtime_id",
	"quantization_id",
	"spark_node",
	"best_full_stack_tok_s",
	"best_full_stack_record",
	"best_full_stack_finite_output",
	"best_full_stack_output_hash",
	"exceeds_15_tok_s",
	"realization_ratio_vs_409",
	"realization_ratio_vs_558",
	"realization_ratio_vs_620",
	"output_head_cap_tok_s",
	"input_prefill_tok_s",
	"suffix_prefill_tok_s",
	"prefix_hit_load_ms",
	"current_primary_blocker",
	"current_secondary_blocker",
	"next_code_change_required",
	"do_not_build_more_scaffolding_until",
	"records",
)


class Ds4PerfIcebergError(ValueError):
	pass


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise Ds4PerfIcebergError(f"{path}: JSON root must be an object")
	return obj


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_number(value: Any) -> bool:
	return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def is_hash(value: Any, allow_empty: bool = False) -> bool:
	if allow_empty and value == "":
		return True
	if not isinstance(value, str):
		return False
	return (value.startswith("sha256:") and len(value) == 71) or (value.startswith("fnv64:") and len(value) == 22)


def first_json_line(text: str) -> dict[str, Any] | None:
	for raw in text.splitlines():
		line = raw.strip()
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


def hash_from_probe(probe: dict[str, Any]) -> str:
	for key in ("output_hash", "logits_sha256", "out_sha256", "tokens_sha256"):
		value = probe.get(key)
		if is_hash(value):
			return str(value)
	for key in ("logits_fnv64", "out_fnv64", "hc_fnv64", "output_fnv64", "tokens_fnv64"):
		value = probe.get(key)
		if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{16}", value):
			return "fnv64:" + value.lower()
	return ""


def finite_from_probe(probe: dict[str, Any], rc: int) -> bool:
	for key in ("logits_nonfinite", "out_nonfinite", "hc_nonfinite", "output_nonfinite"):
		value = probe.get(key)
		if is_number(value):
			return int(value) == 0
	return rc == 0 and hash_from_probe(probe) != ""


def classify_blocker(text: str, rc: int, component_kind: str = "") -> str:
	low = text.lower()
	if rc == 0:
		return "none"
	if "command not found" in low or "unknown option" in low or ("no such file" in low and "ds4" in low):
		return "command_runtime_bug"
	if "out of memory" in low or "cudamalloc" in low or "insufficient memory" in low:
		return "insufficient_memory"
	if "context is destroyed" in low or "context poisoned" in low or "illegal memory" in low:
		return "cuda_context_poisoned"
	if "accelerator stopped startup model cache" in low or ("startup" in low and "preload" in low and "timeout" in low):
		return "startup_preload_timeout"
	if ("q8_0" in low or "attn_out_a" in low) and ("upload" in low or "range" in low or "timeout" in low or "timed out" in low):
		return "q8_0_lazy_upload"
	if "full-slab" in low or "full slab" in low or ("fallback" in low and "expert" in low):
		return "full_slab_fallback"
	if "expert slice" in low and ("miss" in low or "uncached" in low or "cache" in low):
		return "expert_slice_cache_miss"
	if ("model range" in low or "stack_stage" in low or "moe" in low) and ("upload" in low or "copy" in low or "range" in low or "timeout" in low or "timed out" in low):
		return "lazy_moe_range_upload"
	if component_kind == "prefix_hit_load_or_fork":
		return "prefix_prefill_cap"
	if component_kind == "suffix_prefill":
		return "suffix_prefill_cap"
	if component_kind == "kv_pressure":
		return "kv_capacity"
	if component_kind == "activation_transfer":
		return "stage_transfer_cap"
	return "unknown"


def ratios(tok_s: float | None) -> dict[str, float | None]:
	return {
		"vs_" + key: (tok_s / value if tok_s is not None and value > 0.0 else None)
		for key, value in CEILINGS.items()
	}


def parse_prefill_tps(text: str) -> float | None:
	m = re.search(r"prefill:\s*([0-9]+(?:\.[0-9]+)?)\s*t/s", text)
	return float(m.group(1)) if m else None


def build_record(args: argparse.Namespace) -> dict[str, Any]:
	stdout = Path(args.stdout).read_text(encoding="utf-8", errors="replace") if args.stdout else ""
	stderr = Path(args.stderr).read_text(encoding="utf-8", errors="replace") if args.stderr else ""
	rc = int(args.rc)
	probe = first_json_line(stdout) or first_json_line(stderr) or {}
	component_kind = str(args.component_kind)
	best_ms = float_from_probe(probe, "best_ms")
	avg_ms = float_from_probe(probe, "avg_ms")
	tps = float_from_probe(probe, "tokens_per_second", "tok_s", "best_tokens_per_s", "best_rows_per_s")
	heads_per_second = float_from_probe(probe, "heads_per_second", "best_heads_per_s")
	prefill_tps = float_from_probe(probe, "prefill_tokens_per_second")
	if prefill_tps is None:
		prefill_tps = parse_prefill_tps(stdout + "\n" + stderr)
	if component_kind == "output_head" and tps is None:
		tps = heads_per_second
	output_hash = hash_from_probe(probe)
	finite_output = finite_from_probe(probe, rc)
	blocker_text = args.blocker_detail or "\n".join([stderr, stdout])
	blocker_kind = args.blocker_kind or classify_blocker(blocker_text, rc, component_kind)
	output_component = component_kind in {"output_head", "full_stack_decode", "full_stack_batch_no_head", "full_stack_batch_with_head"}
	timing_component = component_kind in {"prefix_miss_prefill", "suffix_prefill"} and is_number(prefill_tps) and float(prefill_tps) > 0.0
	prefix_hit_component = component_kind == "prefix_hit_load_or_fork" and is_number(args.prefix_load_ms)
	aux_component = component_kind in {"kv_pressure", "activation_transfer", "residency_trace"} and rc == 0
	component_success = rc == 0 and ((output_component and finite_output and output_hash != "") or timing_component or prefix_hit_component or aux_component)
	failure_status = args.failure_status or ("success" if component_success else "failed")
	if failure_status != "success" and blocker_kind == "none":
		blocker_kind = classify_blocker(blocker_text, 1, component_kind)
	record = {
		"format": RECORD_FORMAT,
		"artifact_schema_version": SCHEMA_VERSION,
		"artifact_sha256": "",
		"run_id": args.run_id,
		"case_id": args.case_id,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"spark_node": args.spark_node,
		"component_kind": component_kind,
		"batch_size": int(args.batch_size),
		"input_tokens": int(args.input_tokens),
		"context_tokens": int(args.context_tokens),
		"active_sessions": int(args.active_sessions),
		"layers_executed": int(args.layers_executed),
		"includes_output_head": bool(args.includes_output_head),
		"includes_attention": bool(args.includes_attention),
		"includes_kv": bool(args.includes_kv),
		"includes_sampling": bool(args.includes_sampling),
		"component_only": bool(args.component_only),
		"best_ms": best_ms,
		"avg_ms": avg_ms,
		"tokens_per_second": tps,
		"heads_per_second": heads_per_second,
		"prefill_tokens_per_second": prefill_tps,
		"prefix_hit": args.prefix_hit,
		"prefix_tier": args.prefix_tier,
		"prefix_load_ms": args.prefix_load_ms,
		"suffix_prefill_ms": args.suffix_prefill_ms,
		"kv_bytes_reserved": args.kv_bytes_reserved,
		"finite_output": finite_output,
		"output_hash": output_hash,
		"failure_status": failure_status,
		"blocker_kind": blocker_kind,
		"blocker_detail": "" if blocker_kind == "none" else tail_text(blocker_text),
		"compared_ceiling_tok_s": dict(CEILINGS),
		"realization_ratio": ratios(tps),
		"artifact_refs": {"stdout": args.stdout or "", "stderr": args.stderr or ""},
	}
	record["artifact_sha256"] = artifact_sha256(record)
	return record


def validate_record(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in FIXED_SPARK_COUNT_FIELDS:
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	if obj.get("format") != RECORD_FORMAT:
		errors.append(f"format must be {RECORD_FORMAT}")
	if obj.get("artifact_schema_version") != SCHEMA_VERSION:
		errors.append(f"artifact_schema_version must be {SCHEMA_VERSION}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	for key in ("run_id", "case_id", "model_id", "runtime_id", "quantization_id", "spark_node"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	if obj.get("component_kind") not in COMPONENT_KINDS:
		errors.append("component_kind is not declared")
	if obj.get("failure_status") not in FAILURE_STATUS:
		errors.append("failure_status must be success, failed, or not_run")
	if obj.get("blocker_kind") not in BLOCKER_KINDS:
		errors.append("blocker_kind is not declared")
	for key in ("batch_size", "input_tokens", "context_tokens", "active_sessions", "layers_executed"):
		if not isinstance(obj.get(key), int) or isinstance(obj.get(key), bool) or obj.get(key, 0) < 0:
			errors.append(f"{key} must be a non-negative integer")
	for key in ("includes_output_head", "includes_attention", "includes_kv", "includes_sampling", "component_only", "finite_output"):
		if not isinstance(obj.get(key), bool):
			errors.append(f"{key} must be boolean")
	status = obj.get("failure_status")
	is_full_stack = obj.get("component_kind") in {"full_stack_decode", "full_stack_batch_with_head"}
	if status == "success":
		if obj.get("component_kind") in {"output_head", "full_stack_decode", "full_stack_batch_no_head", "full_stack_batch_with_head"}:
			if obj.get("finite_output") is not True:
				errors.append("output/full-stack success requires finite_output=true")
			if not is_hash(obj.get("output_hash")):
				errors.append("output/full-stack success requires output_hash")
		if obj.get("blocker_kind") != "none":
			errors.append("success requires blocker_kind=none")
		if obj.get("component_kind") in {"prefix_miss_prefill", "suffix_prefill"}:
			if not is_number(obj.get("prefill_tokens_per_second")) or float(obj.get("prefill_tokens_per_second")) <= 0.0:
				errors.append("prefill success requires prefill_tokens_per_second > 0")
		if obj.get("component_kind") == "prefix_hit_load_or_fork":
			if not is_number(obj.get("prefix_load_ms")):
				errors.append("prefix-hit success requires prefix_load_ms")
	else:
		if obj.get("blocker_kind") == "none":
			errors.append("failed/not_run records require a non-none blocker_kind")
		if not isinstance(obj.get("blocker_detail"), str) or obj.get("blocker_detail", "").strip() == "":
			errors.append("failed/not_run records require blocker_detail")
	if is_full_stack and status == "success":
		if obj.get("layers_executed", 0) < 43:
			errors.append("full-stack success requires layers_executed >= 43")
		if obj.get("includes_output_head") is not True:
			errors.append("full-stack end-to-end success requires output head")
		if not is_number(obj.get("tokens_per_second")) or float(obj.get("tokens_per_second")) <= 0.0:
			errors.append("full-stack success requires tokens_per_second > 0")
	if obj.get("component_only") and is_full_stack and status == "success":
		errors.append("component_only full-stack success is contradictory")
	tps = obj.get("tokens_per_second")
	if tps is not None and not is_number(tps):
		errors.append("tokens_per_second must be numeric or null")
	for key in ("heads_per_second", "prefill_tokens_per_second", "prefix_load_ms", "suffix_prefill_ms"):
		if obj.get(key) is not None and not is_number(obj.get(key)):
			errors.append(f"{key} must be numeric or null")
	rr = obj.get("realization_ratio")
	if not isinstance(rr, dict):
		errors.append("realization_ratio must be an object")
	else:
		for key in ("vs_synthetic_layer_ceiling", "vs_ffn_envelope_ceiling", "vs_moe_only_ceiling"):
			if key not in rr:
				errors.append(f"realization_ratio.{key} is required")
	return errors


def best_record(records: list[dict[str, Any]], predicate: Any, metric: str) -> dict[str, Any] | None:
	candidates = [r for r in records if predicate(r) and is_number(r.get(metric))]
	if not candidates:
		return None
	return max(candidates, key=lambda r: float(r[metric]))


def choose_primary_blocker(records: list[dict[str, Any]], best_full: dict[str, Any] | None) -> str:
	if best_full is None:
		for kind in ("full_stack_batch_with_head", "full_stack_decode", "full_stack_batch_no_head"):
			for r in records:
				if r.get("component_kind") == kind and r.get("failure_status") != "success":
					return str(r.get("blocker_kind", "unknown"))
		return "unknown"
	output = best_record(records, lambda r: r.get("component_kind") == "output_head" and r.get("failure_status") == "success", "heads_per_second")
	if output and float(output["heads_per_second"]) < 409.0:
		return "output_head_cap"
	return "none"


def next_code_change(blocker: str) -> str:
	if blocker in {"lazy_moe_range_upload", "q8_0_lazy_upload", "startup_preload_timeout", "full_slab_fallback", "expert_slice_cache_miss"}:
		return "Fix CUDA residency first: full-stack/stage preloads must complete without lazy range uploads or fallback slabs."
	if blocker == "cuda_context_poisoned":
		return "Reset/reboot the Spark CUDA context, then rerun the residency probe before changing scheduler code."
	if blocker == "output_head_cap":
		return "Add a batched/head-sharded output projection probe and optimize the vocab projection path."
	if blocker in {"prefix_prefill_cap", "suffix_prefill_cap"}:
		return "Add prefix-hit/fork and suffix-prefill probes, then reduce suffix work or batch prefill."
	if blocker in {"kv_capacity", "kv_bandwidth"}:
		return "Measure KV resident bytes and context-length decode slowdown before scaling active sessions."
	return "Run the smallest failing full-stack case with per-range residency tracing enabled."


def build_summary(args: argparse.Namespace, records: list[dict[str, Any]]) -> dict[str, Any]:
	best_full = best_record(
		records,
		lambda r: r.get("failure_status") == "success"
		and r.get("component_kind") in {"full_stack_decode", "full_stack_batch_with_head"}
		and r.get("layers_executed", 0) >= 43
		and r.get("includes_output_head") is True
		and r.get("finite_output") is True
		and is_hash(r.get("output_hash")),
		"tokens_per_second",
	)
	output = best_record(
		records,
		lambda r: r.get("failure_status") == "success" and r.get("component_kind") == "output_head",
		"heads_per_second",
	)
	prefill = best_record(
		records,
		lambda r: r.get("failure_status") == "success" and r.get("component_kind") == "prefix_miss_prefill",
		"prefill_tokens_per_second",
	)
	suffix = best_record(
		records,
		lambda r: r.get("failure_status") == "success" and r.get("component_kind") == "suffix_prefill",
		"prefill_tokens_per_second",
	)
	prefix_hit = best_record(
		records,
		lambda r: r.get("failure_status") == "success" and r.get("component_kind") == "prefix_hit_load_or_fork",
		"prefix_load_ms",
	)
	best_tok = float(best_full["tokens_per_second"]) if best_full else None
	primary = choose_primary_blocker(records, best_full)
	second = "none"
	if primary != "none":
		for r in records:
			if r.get("failure_status") != "success" and r.get("blocker_kind") not in {primary, "none"}:
				second = str(r.get("blocker_kind"))
				break
	summary = {
		"format": SUMMARY_FORMAT,
		"artifact_schema_version": SCHEMA_VERSION,
		"artifact_sha256": "",
		"run_id": args.run_id,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"spark_node": args.spark_node,
		"best_full_stack_tok_s": best_tok,
		"best_full_stack_record": best_full.get("case_id") if best_full else "",
		"best_full_stack_finite_output": bool(best_full and best_full.get("finite_output")),
		"best_full_stack_output_hash": best_full.get("output_hash", "") if best_full else "",
		"exceeds_15_tok_s": bool(best_tok is not None and best_tok > 15.0),
		"realization_ratio_vs_409": best_tok / 409.0 if best_tok is not None else None,
		"realization_ratio_vs_558": best_tok / 558.0 if best_tok is not None else None,
		"realization_ratio_vs_620": best_tok / 620.0 if best_tok is not None else None,
		"output_head_cap_tok_s": float(output["heads_per_second"]) if output else None,
		"input_prefill_tok_s": float(prefill["prefill_tokens_per_second"]) if prefill else None,
		"suffix_prefill_tok_s": float(suffix["prefill_tokens_per_second"]) if suffix else None,
		"prefix_hit_load_ms": float(prefix_hit["prefix_load_ms"]) if prefix_hit else None,
		"current_primary_blocker": primary,
		"current_secondary_blocker": second,
		"next_code_change_required": next_code_change(primary),
		"do_not_build_more_scaffolding_until": "full-stack B>=16 completes with finite output/hash" if best_tok is None or best_tok <= 15.0 else "slowest measured lifecycle stage is optimized against a finite-output full-stack baseline",
		"baseline_tok_s": BASELINE_TOK_S,
		"component_ceiling_tok_s": dict(CEILINGS),
		"records": [r.get("case_id") for r in records],
	}
	summary["artifact_sha256"] = artifact_sha256(summary)
	return summary


def validate_summary(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in SUMMARY_REQUIRED:
		if key not in obj:
			errors.append(f"missing required field: {key}")
	for key in FIXED_SPARK_COUNT_FIELDS:
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	if obj.get("format") != SUMMARY_FORMAT:
		errors.append(f"format must be {SUMMARY_FORMAT}")
	if obj.get("artifact_schema_version") != SCHEMA_VERSION:
		errors.append(f"artifact_schema_version must be {SCHEMA_VERSION}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	for key in ("run_id", "model_id", "runtime_id", "quantization_id", "spark_node", "current_primary_blocker", "next_code_change_required", "do_not_build_more_scaffolding_until"):
		if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
			errors.append(f"{key} must be a non-empty string")
	if obj.get("current_primary_blocker") not in BLOCKER_KINDS:
		errors.append("current_primary_blocker is not declared")
	if obj.get("current_secondary_blocker") not in BLOCKER_KINDS:
		errors.append("current_secondary_blocker is not declared")
	if not isinstance(obj.get("exceeds_15_tok_s"), bool):
		errors.append("exceeds_15_tok_s must be boolean")
	best = obj.get("best_full_stack_tok_s")
	if best is not None:
		if not is_number(best) or float(best) <= 0.0:
			errors.append("best_full_stack_tok_s must be positive numeric or null")
		if obj.get("best_full_stack_finite_output") is not True:
			errors.append("full-stack speed claim requires finite output")
		if not is_hash(obj.get("best_full_stack_output_hash")):
			errors.append("full-stack speed claim requires output hash")
		if not isinstance(obj.get("best_full_stack_record"), str) or obj.get("best_full_stack_record") == "":
			errors.append("full-stack speed claim requires best_full_stack_record")
	else:
		if obj.get("exceeds_15_tok_s") is True:
			errors.append("exceeds_15_tok_s cannot be true without best_full_stack_tok_s")
		if obj.get("current_primary_blocker") == "none":
			errors.append("blocked summary requires a primary blocker")
	for key in ("realization_ratio_vs_409", "realization_ratio_vs_558", "realization_ratio_vs_620", "output_head_cap_tok_s", "input_prefill_tok_s", "suffix_prefill_tok_s", "prefix_hit_load_ms"):
		if obj.get(key) is not None and not is_number(obj.get(key)):
			errors.append(f"{key} must be numeric or null")
	if not isinstance(obj.get("records"), list):
		errors.append("records must be a list")
	return errors


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	if obj.get("format") == RECORD_FORMAT:
		return validate_record(obj)
	if obj.get("format") == SUMMARY_FORMAT:
		return validate_summary(obj)
	return ["unknown format"]


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


def cmd_record(args: argparse.Namespace) -> int:
	record = build_record(args)
	errors = validate_record(record)
	if errors:
		for item in errors:
			print(f"record: {item}", file=sys.stderr)
		return 1
	write_json(Path(args.out), record)
	print(f"wrote: {args.out}")
	return 0


def cmd_summarize(args: argparse.Namespace) -> int:
	records = [load_json(Path(item)) for item in args.records]
	for record in records:
		errors = validate_record(record)
		if errors:
			for item in errors:
				print(f"{record.get('case_id', '<unknown>')}: {item}", file=sys.stderr)
			return 1
	summary = build_summary(args, records)
	errors = validate_summary(summary)
	if errors:
		for item in errors:
			print(f"summary: {item}", file=sys.stderr)
		return 1
	write_json(Path(args.out), summary)
	print(f"wrote: {args.out}")
	return 0


def add_identity_args(parser: argparse.ArgumentParser) -> None:
	parser.add_argument("--run-id", required=True)
	parser.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	parser.add_argument("--runtime-id", default="antirez-ds4-cuda-stack-probe")
	parser.add_argument("--quantization-id", default="DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf")
	parser.add_argument("--spark-node", required=True)


def main() -> int:
	if len(sys.argv) > 1 and sys.argv[1] not in ("record", "summarize", "validate", "-h", "--help"):
		return cmd_validate([Path(item) for item in sys.argv[1:]], False)
	parser = argparse.ArgumentParser(description=__doc__)
	sub = parser.add_subparsers(dest="cmd")
	record = sub.add_parser("record")
	add_identity_args(record)
	record.add_argument("--out", required=True)
	record.add_argument("--case-id", required=True)
	record.add_argument("--component-kind", choices=sorted(COMPONENT_KINDS), required=True)
	record.add_argument("--batch-size", type=int, default=0)
	record.add_argument("--input-tokens", type=int, default=0)
	record.add_argument("--context-tokens", type=int, default=0)
	record.add_argument("--active-sessions", type=int, default=0)
	record.add_argument("--layers-executed", type=int, default=0)
	record.add_argument("--includes-output-head", action="store_true")
	record.add_argument("--includes-attention", action="store_true")
	record.add_argument("--includes-kv", action="store_true")
	record.add_argument("--includes-sampling", action="store_true")
	record.add_argument("--component-only", action="store_true")
	record.add_argument("--warmup-policy", default="")
	record.add_argument("--residency-policy", default="")
	record.add_argument("--prefix-hit", choices=("true", "false", "unknown"), default="unknown")
	record.add_argument("--prefix-tier", default="")
	record.add_argument("--prefix-load-ms", type=float, default=None)
	record.add_argument("--suffix-prefill-ms", type=float, default=None)
	record.add_argument("--kv-bytes-reserved", type=int, default=0)
	record.add_argument("--stdout", default="")
	record.add_argument("--stderr", default="")
	record.add_argument("--rc", type=int, default=0)
	record.add_argument("--failure-status", choices=sorted(FAILURE_STATUS), default="")
	record.add_argument("--blocker-kind", choices=sorted(BLOCKER_KINDS), default="")
	record.add_argument("--blocker-detail", default="")
	record.set_defaults(func=cmd_record)
	summarize = sub.add_parser("summarize")
	add_identity_args(summarize)
	summarize.add_argument("--out", required=True)
	summarize.add_argument("records", nargs="+")
	summarize.set_defaults(func=cmd_summarize)
	validate = sub.add_parser("validate")
	validate.add_argument("artifacts", nargs="+")
	validate.add_argument("--fix-hash", action="store_true")
	args = parser.parse_args()
	if args.cmd == "record":
		return args.func(args)
	if args.cmd == "summarize":
		return args.func(args)
	if args.cmd == "validate":
		return cmd_validate([Path(item) for item in args.artifacts], bool(args.fix_hash))
	parser.print_help()
	return 2


if __name__ == "__main__":
	raise SystemExit(main())
