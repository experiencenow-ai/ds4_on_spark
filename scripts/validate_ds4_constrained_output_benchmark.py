#!/usr/bin/env python3
"""Build and validate DS4 B=512 constrained short-output benchmark artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


FORMAT = "ds4-b512-constrained-output-benchmark-v1"
CONSTRAINED_CANDIDATE_KINDS = {"numeric_ids", "digits_spaces_newline", "explicit_token_set"}
CONTROL_CANDIDATE_KINDS = {"full_vocab"}
CANDIDATE_KINDS = CONSTRAINED_CANDIDATE_KINDS | CONTROL_CANDIDATE_KINDS
PROMPT_PATTERNS = {"shared_prefix_compact_suffix", "decode_only"}
PREFIX_MODES = {"hit_fork", "miss_prepare", "no_prefix"}
OUTPUT_TARGETS = {1, 4, 8}
PRODUCTION_HOOKS = {"shared_prefix_hit_fork_runtime"}
COMMIT_LANES = {"constrained_candidate_commit", "full_vocab_output_projection_control"}
REQUEST_SHAPES = {"b512_separate_rows"}


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
	tmp = copy.deepcopy(obj)
	tmp.pop("artifact_sha256", None)
	tmp.pop("artifact_hash", None)
	return sha256_obj(tmp)


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_i32_csv(text: str) -> list[int]:
	out: list[int] = []
	if text.strip() == "":
		return out
	for raw in text.split(","):
		item = raw.strip()
		if item == "":
			continue
		value = int(item)
		if value < 0:
			raise ValueError("candidate token ids must be non-negative")
		out.append(value)
	return out


def parity_flags_match(artifact_flags: dict[str, Any], parity_flags: dict[str, Any]) -> bool:
	for key,value in parity_flags.items():
		if str(artifact_flags.get(key, "")) != str(value):
			return False
	return True


def input_provenance(flags: dict[str, Any], runtime_hook: str, measurement_source: str) -> str:
	if "DS4_CUDA_STACK_PROBE_ROW_TOKEN_IDS" in flags:
		return "row_token_suffix_probe"
	if "derived" in measurement_source:
		return "derived_multistep_kv_loop"
	if runtime_hook in PRODUCTION_HOOKS:
		return "shared_prefix_hit_fork_runtime"
	return runtime_hook


def build_from_end_to_end(args: argparse.Namespace) -> dict[str, Any]:
	src = load_json(Path(args.end_to_end_artifact))
	parity = load_json(Path(args.parity_artifact))
	candidate_ids = parse_i32_csv(args.candidate_token_ids)
	kind = args.candidate_vocabulary_kind
	if kind != "full_vocab" and len(candidate_ids) == 0:
		raise ValueError("constrained candidate artifacts require candidate token ids")
	if kind == "full_vocab" and len(candidate_ids) != 0:
		raise ValueError("full_vocab control must not declare candidate token ids")
	flags = dict(src.get("optimized_kernel_flags", {}))
	parity_flags = dict(parity.get("optimized_kernel_flags", {}))
	runtime_hook = args.runtime_hook_status
	production = bool(args.production_generation_eligible)
	measurement_source = str(src.get("measurement_source", ""))
	commit_lane = "full_vocab_output_projection_control" if kind == "full_vocab" else "constrained_candidate_commit"
	obj: dict[str, Any] = {
		"format": FORMAT,
		"run_id": args.run_id,
		"provider_id": str(src.get("provider_id", "")),
		"model_id": str(src.get("model_id", "")),
		"runtime_id": str(src.get("runtime_id", "")),
		"quantization_id": str(src.get("quantization_id", "")),
		"optimized_kernel_flags": flags,
		"batch_size": int(src.get("batch_size", 0)),
		"microbatch_count": int(src.get("microbatch_count", 0)),
		"prompt_pattern": str(src.get("prompt_pattern", "")),
		"candidate_vocabulary_kind": kind,
		"candidate_token_count": len(candidate_ids),
		"candidate_token_ids": candidate_ids,
		"candidate_token_ids_sha256": sha256_obj(candidate_ids) if candidate_ids else "",
		"commit_lane": commit_lane,
		"request_shape": "b512_separate_rows",
		"token_commit_mode": str(src.get("token_commit_mode", "")),
		"runtime_hook_status": runtime_hook,
		"input_provenance": input_provenance(flags, runtime_hook, measurement_source),
		"output_token_target": int(src.get("output_token_target", 0)),
		"prefix_mode": str(src.get("prefix_mode", "")),
		"prefix_prepare_ms": float(src.get("prefix_prepare_ms", 0.0)),
		"prefix_load_or_fork_ms": float(src.get("prefix_load_or_fork_ms", 0.0)),
		"suffix_tokens_per_row": int(src.get("suffix_tokens_per_row", 0)),
		"suffix_prefill_ms": float(src.get("suffix_prefill_ms", 0.0)),
		"suffix_prefill_tokens_per_s": float(src.get("suffix_prefill_tokens_per_s", 0.0)),
		"decode_steps": int(src.get("decode_steps", 0)),
		"decode_ms": float(src.get("decode_ms", 0.0)),
		"constrained_commit_ms": float(src.get("token_commit_ms", 0.0)) if kind != "full_vocab" else 0.0,
		"full_vocab_commit_ms": float(src.get("token_commit_ms", 0.0)) if kind == "full_vocab" else 0.0,
		"token_hash": str(src.get("token_hash", "")),
		"committed_token_ids_present": bool(src.get("committed_token_ids_present")),
		"end_to_end_wall_ms": float(src.get("end_to_end_wall_ms", 0.0)),
		"end_to_end_output_tokens_per_s": float(src.get("end_to_end_output_tokens_per_s", 0.0)),
		"per_row_avg_token_s": float(src.get("per_row_avg_token_s", 0.0)),
		"final_logits_hash": str(src.get("final_logits_hash", "")),
		"finite_output": bool(src.get("finite_output")),
		"parity_artifact_sha256": str(parity.get("artifact_sha256", "")),
		"parity_scope": str(parity.get("parity_scope", "")),
		"parity_status": str(parity.get("parity_status", "")),
		"parity_optimized_kernel_flags": parity_flags,
		"optimized_kernel_flags_match_parity": parity_flags_match(flags, parity_flags),
		"production_generation_eligible": production,
		"blocker_kind": str(src.get("blocker_kind", "none")),
		"blocker_detail": str(src.get("blocker_detail", "")),
		"source_artifact": args.end_to_end_artifact,
		"source_artifact_sha256": str(src.get("artifact_sha256", "")),
		"artifact_refs": [
			{"name": "end_to_end_decode_artifact", "path": args.end_to_end_artifact, "sha256": str(src.get("artifact_sha256", ""))},
			{"name": "parity_artifact", "path": args.parity_artifact, "sha256": str(parity.get("artifact_sha256", ""))},
		],
	}
	if "measurement_source" in src:
		obj["measurement_source"] = src["measurement_source"]
	if "runtime_hook_patch" in src:
		obj["runtime_hook_patch"] = src["runtime_hook_patch"]
	obj["artifact_sha256"] = artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	return obj


def expect_string(errors: list[str], obj: dict[str, Any], key: str) -> None:
	if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
		errors.append(f"{key} must be a non-empty string")


def expect_number(errors: list[str], obj: dict[str, Any], key: str, minimum: float = 0.0) -> None:
	if not isinstance(obj.get(key), (int, float)) or float(obj.get(key, 0.0)) < minimum:
		errors.append(f"{key} must be a number >= {minimum}")


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in ("format", "run_id", "provider_id", "model_id", "runtime_id", "quantization_id", "prompt_pattern", "candidate_vocabulary_kind", "commit_lane", "request_shape", "input_provenance", "prefix_mode", "token_hash", "parity_artifact_sha256", "blocker_kind", "artifact_sha256", "artifact_hash"):
		expect_string(errors, obj, key)
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	if obj.get("artifact_hash") != obj.get("artifact_sha256"):
		errors.append("artifact_hash must match artifact_sha256")
	if obj.get("batch_size") != 512:
		errors.append("batch_size must be 512")
	if obj.get("microbatch_count") != 16:
		errors.append("microbatch_count must be 16")
	if obj.get("prompt_pattern") not in PROMPT_PATTERNS:
		errors.append("prompt_pattern is invalid")
	if obj.get("candidate_vocabulary_kind") not in CANDIDATE_KINDS:
		errors.append("candidate_vocabulary_kind is invalid")
	if obj.get("commit_lane") not in COMMIT_LANES:
		errors.append("commit_lane is invalid")
	if obj.get("request_shape") not in REQUEST_SHAPES:
		errors.append("request_shape must be b512_separate_rows")
	if obj.get("prefix_mode") not in PREFIX_MODES:
		errors.append("prefix_mode is invalid")
	if obj.get("output_token_target") not in OUTPUT_TARGETS:
		errors.append("output_token_target must be 1, 4, or 8")
	for key in ("prefix_prepare_ms", "prefix_load_or_fork_ms", "suffix_prefill_ms", "suffix_prefill_tokens_per_s", "decode_ms", "constrained_commit_ms", "full_vocab_commit_ms", "end_to_end_wall_ms", "end_to_end_output_tokens_per_s", "per_row_avg_token_s"):
		expect_number(errors, obj, key)
	if not isinstance(obj.get("optimized_kernel_flags"), dict):
		errors.append("optimized_kernel_flags must be an object")
	if not isinstance(obj.get("parity_optimized_kernel_flags"), dict):
		errors.append("parity_optimized_kernel_flags must be an object")
	if obj.get("optimized_kernel_flags_match_parity") is not True:
		errors.append("optimized_kernel_flags must include parity optimized flags")
	if not str(obj.get("parity_artifact_sha256", "")).startswith("sha256:"):
		errors.append("parity_artifact_sha256 must be sha256")
	if obj.get("parity_status") != "passed":
		errors.append("parity_status must be passed")
	if obj.get("parity_scope") not in ("cross_spark_ppn", "parity_passed_prefill_decode"):
		errors.append("parity_scope must be cross_spark_ppn or stronger")
	if not str(obj.get("token_hash", "")).startswith("fnv64:"):
		errors.append("token_hash must be fnv64")
	if not str(obj.get("final_logits_hash", "")).startswith("fnv64:"):
		errors.append("final_logits_hash must be fnv64")
	if obj.get("finite_output") is not True:
		errors.append("finite_output must be true")
	if obj.get("committed_token_ids_present") is not True:
		errors.append("committed_token_ids_present must be true")
	if obj.get("blocker_kind") == "none":
		if float(obj.get("end_to_end_output_tokens_per_s", 0.0)) <= 0.0:
			errors.append("successful benchmark requires positive end_to_end_output_tokens_per_s")
	else:
		if obj.get("production_generation_eligible") is True:
			errors.append("blocked benchmark cannot be production eligible")
		if not isinstance(obj.get("blocker_detail"), str) or obj.get("blocker_detail", "").strip() == "":
			errors.append("blocked benchmark requires blocker_detail")
	kind = obj.get("candidate_vocabulary_kind")
	candidate_ids = obj.get("candidate_token_ids")
	if not isinstance(candidate_ids, list):
		errors.append("candidate_token_ids must be a list")
	else:
		if kind == "full_vocab":
			if obj.get("commit_lane") != "full_vocab_output_projection_control":
				errors.append("full_vocab control requires full_vocab_output_projection_control commit_lane")
			if len(candidate_ids) != 0 or obj.get("candidate_token_count") != 0:
				errors.append("full_vocab control must not declare constrained candidate ids")
			if obj.get("token_commit_mode") != "full_vocab_batch_head":
				errors.append("full_vocab control requires full_vocab_batch_head token_commit_mode")
			if float(obj.get("full_vocab_commit_ms", 0.0)) <= 0.0:
				errors.append("full_vocab control requires full_vocab_commit_ms")
		else:
			if obj.get("commit_lane") != "constrained_candidate_commit":
				errors.append("constrained benchmark requires constrained_candidate_commit commit_lane")
			if len(candidate_ids) == 0:
				errors.append("constrained benchmark requires candidate_token_ids")
			if obj.get("candidate_token_count") != len(candidate_ids):
				errors.append("candidate_token_count must match candidate_token_ids")
			if len(set(candidate_ids)) != len(candidate_ids):
				errors.append("candidate_token_ids must be unique")
			if not all(isinstance(v, int) and v >= 0 for v in candidate_ids):
				errors.append("candidate_token_ids must be non-negative integers")
			if not str(obj.get("candidate_token_ids_sha256", "")).startswith("sha256:"):
				errors.append("candidate_token_ids_sha256 must be sha256 for constrained benchmark")
			if obj.get("token_commit_mode") != "constrained_vocab_cpu_top1":
				errors.append("constrained benchmark requires constrained_vocab_cpu_top1 token_commit_mode")
			if float(obj.get("constrained_commit_ms", 0.0)) <= 0.0:
				errors.append("constrained benchmark requires constrained_commit_ms")
	if obj.get("prompt_pattern") == "decode_only" and obj.get("prefix_mode") != "no_prefix":
		errors.append("decode_only control must use no_prefix")
	if obj.get("prompt_pattern") == "shared_prefix_compact_suffix" and obj.get("prefix_mode") == "no_prefix":
		errors.append("shared-prefix benchmark must not use no_prefix")
	if obj.get("production_generation_eligible") is True:
		if kind == "full_vocab":
			errors.append("full-vocab control is not the constrained-output production lane")
		if kind not in CONSTRAINED_CANDIDATE_KINDS:
			errors.append("production eligibility requires a constrained candidate vocabulary kind")
		if obj.get("commit_lane") != "constrained_candidate_commit":
			errors.append("production eligibility requires constrained_candidate_commit")
		if obj.get("request_shape") != "b512_separate_rows":
			errors.append("production eligibility requires B=512 separate rows")
		if obj.get("prompt_pattern") != "shared_prefix_compact_suffix" or obj.get("prefix_mode") != "hit_fork":
			errors.append("production eligibility requires shared_prefix_compact_suffix hit_fork")
		if obj.get("runtime_hook_status") not in PRODUCTION_HOOKS:
			errors.append("production eligibility requires a real shared-prefix hit/fork runtime hook")
		if obj.get("input_provenance") != "shared_prefix_hit_fork_runtime":
			errors.append("production eligibility requires input_provenance=shared_prefix_hit_fork_runtime")
		if "DS4_CUDA_STACK_PROBE_ROW_TOKEN_IDS" in obj.get("optimized_kernel_flags", {}):
			errors.append("production eligibility cannot use row-token suffix probe input")
		if "derived" in str(obj.get("measurement_source", "")):
			errors.append("production eligibility cannot use derived measurement_source")
	return errors


def main() -> int:
	if len(sys.argv) > 1 and sys.argv[1] not in ("build-from-end-to-end", "validate", "-h", "--help"):
		failed = False
		for raw in sys.argv[1:]:
			path = Path(raw)
			try:
				errors = validate_artifact(load_json(path))
			except (OSError, ValueError, json.JSONDecodeError) as exc:
				print(str(exc))
				return 1
			if errors:
				failed = True
				for error in errors:
					print(f"error: {path}: {error}")
			else:
				print(f"ok: {path}")
		return 2 if failed else 0
	ap = argparse.ArgumentParser()
	sub = ap.add_subparsers(dest="cmd", required=True)
	build = sub.add_parser("build-from-end-to-end")
	build.add_argument("--run-id", required=True)
	build.add_argument("--end-to-end-artifact", required=True)
	build.add_argument("--parity-artifact", required=True)
	build.add_argument("--candidate-vocabulary-kind", required=True, choices=sorted(CANDIDATE_KINDS))
	build.add_argument("--candidate-token-ids", default="")
	build.add_argument("--runtime-hook-status", required=True)
	build.add_argument("--production-generation-eligible", action="store_true")
	build.add_argument("--out", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	args = ap.parse_args()
	try:
		if args.cmd == "build-from-end-to-end":
			obj = build_from_end_to_end(args)
			errors = validate_artifact(obj)
			if errors:
				raise ValueError("; ".join(errors))
			write_json(Path(args.out), obj)
			print(json.dumps(obj, indent=2, sort_keys=True))
		else:
			failed = False
			for raw in args.paths:
				path = Path(raw)
				errors = validate_artifact(load_json(path))
				if errors:
					failed = True
					for error in errors:
						print(f"error: {path}: {error}")
				else:
					print(f"ok: {path}")
			if failed:
				return 2
	except (OSError, ValueError, json.JSONDecodeError) as exc:
		print(str(exc))
		return 1
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
