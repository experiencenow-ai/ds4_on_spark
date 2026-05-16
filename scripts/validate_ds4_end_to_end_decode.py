#!/usr/bin/env python3
"""Build and validate DS4 B=512 end-to-end decode benchmark artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any


FORMAT = "ds4-b512-end-to-end-decode-v1"
PROMPT_PATTERNS = {"shared_prefix_compact_suffix", "unique_prefix", "decode_only"}
PREFIX_MODES = {"miss_prepare", "hit_fork", "no_prefix"}
OUTPUT_TARGETS = {1, 4, 8, 16}
KV_UPDATE_MODES = {"none", "present", "blocked"}


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


def nested_last_ms(stage: dict[str, Any]) -> float:
	finish = stage.get("streaming_schedule_finish_ms")
	if isinstance(finish, list) and finish and isinstance(finish[-1], list) and finish[-1]:
		return float(finish[-1][-1])
	achieved = float(stage.get("achieved_streaming_rows_per_s", 0.0))
	batch = int(stage.get("batch_size", 0))
	mb = int(stage.get("microbatch_count", 0))
	if achieved > 0.0 and batch > 0 and mb > 0:
		return (batch * mb * 1000.0 / achieved)
	return 0.0


def max_number(values: Any) -> float:
	if not isinstance(values, list):
		return 0.0
	nums = [float(v) for v in values if isinstance(v, (int, float))]
	return max(nums) if nums else 0.0


def build_from_stage(args: argparse.Namespace) -> dict[str, Any]:
	stage = load_json(Path(args.stage_handoff))
	parity = load_json(Path(args.parity_artifact))
	batch = int(stage.get("batch_size", 0))
	mb = int(stage.get("microbatch_count", 0))
	decode_ms = nested_last_ms(stage)
	token_commit_ms = float(stage.get("token_commit_ms", max_number(stage.get("token_commit_ms_by_microbatch"))))
	prefix_prepare_ms = float(args.prefix_prepare_ms)
	prefix_load_ms = float(args.prefix_load_or_fork_ms)
	suffix_prefill_ms = float(args.suffix_prefill_ms)
	result_collection_ms = token_commit_ms
	end_to_end_ms = prefix_prepare_ms + prefix_load_ms + suffix_prefill_ms + decode_ms + result_collection_ms
	output_tokens = batch * mb * int(args.output_token_target)
	obj = base_artifact(args)
	obj.update({
		"model_id": str(stage.get("model_id", "")),
		"runtime_id": str(stage.get("runtime_id", "")),
		"quantization_id": str(stage.get("quantization_id", "")),
		"optimized_kernel_flags": dict(stage.get("stage_env", {})),
		"batch_size": batch,
		"microbatch_count": mb,
		"prefix_prepare_ms": prefix_prepare_ms,
		"prefix_load_or_fork_ms": prefix_load_ms,
		"suffix_tokens_per_row": int(args.suffix_tokens_per_row),
		"suffix_prefill_ms": suffix_prefill_ms,
		"suffix_prefill_tokens_per_s": (batch * int(args.suffix_tokens_per_row) * 1000.0 / suffix_prefill_ms) if suffix_prefill_ms > 0.0 else 0.0,
		"decode_steps": int(args.output_token_target),
		"per_step_decode_ms": [decode_ms] if int(args.output_token_target) == 1 else [],
		"kv_update_mode": "none" if int(args.output_token_target) == 1 else "blocked",
		"kv_update_ms": 0.0,
		"committed_token_ids_by_step": [stage.get("committed_token_ids", [])] if int(args.output_token_target) == 1 and stage.get("committed_token_ids_present") else [],
		"token_hashes_by_step": [str(stage.get("token_hash", ""))] if int(args.output_token_target) == 1 and stage.get("token_hash") else [],
		"decode_ms": decode_ms,
		"decode_only_rows_per_s": float(stage.get("achieved_streaming_rows_per_s", 0.0)),
		"output_head_ms": float(args.output_head_ms),
		"token_commit_ms": token_commit_ms,
		"committed_token_ids_present": bool(stage.get("committed_token_ids_present")),
		"token_hash": str(stage.get("token_hash", "")),
		"result_collection_ms": result_collection_ms,
		"end_to_end_wall_ms": end_to_end_ms,
		"end_to_end_output_tokens_per_s": (output_tokens * 1000.0 / end_to_end_ms) if end_to_end_ms > 0.0 else 0.0,
		"per_row_avg_token_s": (end_to_end_ms / 1000.0 / output_tokens) if output_tokens > 0 else 0.0,
		"final_logits_hash": str(stage.get("final_logits_hash", "")),
		"finite_output": bool(stage.get("final_output_finite")),
		"parity_artifact_sha256": str(parity.get("artifact_sha256", "")),
		"production_generation_eligible": bool(args.production_generation_eligible),
		"blocker_kind": "none",
		"blocker_detail": "",
		"artifact_refs": [
			{"name": "stage_handoff", "path": args.stage_handoff},
			{"name": "parity_artifact", "path": args.parity_artifact, "sha256": str(parity.get("artifact_sha256", ""))},
		],
	})
	obj["artifact_sha256"] = artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	return obj


def base_artifact(args: argparse.Namespace) -> dict[str, Any]:
	return {
		"format": FORMAT,
		"run_id": args.run_id,
		"provider_id": args.provider_id,
		"model_id": args.model_id,
		"runtime_id": args.runtime_id,
		"quantization_id": args.quantization_id,
		"optimized_kernel_flags": {},
		"batch_size": 512,
		"microbatch_count": 16,
		"prompt_pattern": args.prompt_pattern,
		"output_token_target": int(args.output_token_target),
		"prefix_mode": args.prefix_mode,
		"prefix_prepare_ms": 0.0,
		"prefix_load_or_fork_ms": 0.0,
		"suffix_tokens_per_row": 0,
		"suffix_prefill_ms": 0.0,
		"suffix_prefill_tokens_per_s": 0.0,
		"decode_steps": int(args.output_token_target),
		"per_step_decode_ms": [],
		"kv_update_mode": "none",
		"kv_update_ms": 0.0,
		"committed_token_ids_by_step": [],
		"token_hashes_by_step": [],
		"decode_ms": 0.0,
		"decode_only_rows_per_s": 0.0,
		"output_head_ms": 0.0,
		"token_commit_ms": 0.0,
		"committed_token_ids_present": False,
		"token_hash": "",
		"result_collection_ms": 0.0,
		"end_to_end_wall_ms": 0.0,
		"end_to_end_output_tokens_per_s": 0.0,
		"per_row_avg_token_s": 0.0,
		"final_logits_hash": "",
		"finite_output": False,
		"parity_artifact_sha256": getattr(args, "parity_artifact_sha256", ""),
		"production_generation_eligible": False,
		"blocker_kind": getattr(args, "blocker_kind", "none"),
		"blocker_detail": getattr(args, "blocker_detail", ""),
		"artifact_refs": [],
	}


def build_blocked(args: argparse.Namespace) -> dict[str, Any]:
	obj = base_artifact(args)
	if int(args.output_token_target) > 1 or "kv" in str(args.blocker_kind).lower():
		obj["kv_update_mode"] = "blocked"
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
	for key in ("format", "run_id", "provider_id", "model_id", "runtime_id", "quantization_id", "prompt_pattern", "prefix_mode", "blocker_kind", "artifact_sha256", "artifact_hash"):
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
	if obj.get("prefix_mode") not in PREFIX_MODES:
		errors.append("prefix_mode is invalid")
	if obj.get("output_token_target") not in OUTPUT_TARGETS:
		errors.append("output_token_target must be 1, 4, 8, or 16")
	for key in ("prefix_prepare_ms", "prefix_load_or_fork_ms", "suffix_prefill_ms", "suffix_prefill_tokens_per_s", "decode_ms", "decode_only_rows_per_s", "output_head_ms", "token_commit_ms", "result_collection_ms", "end_to_end_wall_ms", "end_to_end_output_tokens_per_s", "per_row_avg_token_s"):
		expect_number(errors, obj, key)
	if not isinstance(obj.get("suffix_tokens_per_row"), int) or obj.get("suffix_tokens_per_row", -1) < 0:
		errors.append("suffix_tokens_per_row must be a non-negative integer")
	if not isinstance(obj.get("decode_steps"), int) or obj.get("decode_steps", 0) <= 0:
		errors.append("decode_steps must be a positive integer")
	if obj.get("kv_update_mode") not in KV_UPDATE_MODES:
		errors.append("kv_update_mode must be none, present, or blocked")
	per_step = obj.get("per_step_decode_ms")
	if not isinstance(per_step, list):
		errors.append("per_step_decode_ms must be a list")
	elif obj.get("blocker_kind") == "none":
		if len(per_step) != obj.get("decode_steps"):
			errors.append("per_step_decode_ms length must match decode_steps")
		elif not all(isinstance(v, (int, float)) and v >= 0.0 for v in per_step):
			errors.append("per_step_decode_ms must contain non-negative numbers")
		elif not math.isclose(float(obj.get("decode_ms", 0.0)), sum(float(v) for v in per_step), rel_tol=0.05, abs_tol=1.0):
			errors.append("decode_ms must approximately equal sum(per_step_decode_ms)")
	token_hashes = obj.get("token_hashes_by_step")
	token_ids_by_step = obj.get("committed_token_ids_by_step")
	if not isinstance(token_hashes, list):
		errors.append("token_hashes_by_step must be a list")
	if not isinstance(token_ids_by_step, list):
		errors.append("committed_token_ids_by_step must be a list")
	expect_number(errors, obj, "kv_update_ms")
	if not isinstance(obj.get("optimized_kernel_flags"), dict):
		errors.append("optimized_kernel_flags must be an object")
	success = obj.get("blocker_kind") == "none"
	if success:
		if obj.get("finite_output") is not True:
			errors.append("successful decode benchmark requires finite_output=true")
		for key in ("final_logits_hash", "token_hash", "parity_artifact_sha256"):
			expect_string(errors, obj, key)
		if not str(obj.get("final_logits_hash", "")).startswith("fnv64:"):
			errors.append("final_logits_hash must be fnv64 for current benchmark")
		if not str(obj.get("token_hash", "")).startswith("fnv64:"):
			errors.append("token_hash must be fnv64 for current benchmark")
		if not str(obj.get("parity_artifact_sha256", "")).startswith("sha256:"):
			errors.append("parity_artifact_sha256 must be sha256")
		if obj.get("committed_token_ids_present") is not True:
			errors.append("successful decode benchmark requires committed token ids")
		if obj.get("decode_steps", 0) > 1 and obj.get("kv_update_mode") != "present":
			errors.append("multi-step decode benchmark requires kv_update_mode=present")
		if isinstance(token_hashes, list) and len(token_hashes) != obj.get("decode_steps"):
			errors.append("token_hashes_by_step length must match decode_steps")
		if isinstance(token_ids_by_step, list) and len(token_ids_by_step) != obj.get("decode_steps"):
			errors.append("committed_token_ids_by_step length must match decode_steps")
		if float(obj.get("end_to_end_output_tokens_per_s", 0.0)) <= 0.0:
			errors.append("successful decode benchmark requires positive end_to_end_output_tokens_per_s")
	else:
		if obj.get("production_generation_eligible") is True:
			errors.append("blocked decode benchmark must not claim production_generation_eligible")
		if obj.get("blocker_kind") in ("", None):
			errors.append("blocked decode benchmark requires blocker_kind")
		if not isinstance(obj.get("blocker_detail"), str) or obj.get("blocker_detail", "").strip() == "":
			errors.append("blocked decode benchmark requires blocker_detail")
	if obj.get("production_generation_eligible") is True:
		if not success or obj.get("committed_token_ids_present") is not True or obj.get("finite_output") is not True:
			errors.append("production_generation_eligible requires unblocked finite output with committed token ids")
	return errors


def add_common(p: argparse.ArgumentParser) -> None:
	p.add_argument("--run-id", required=True)
	p.add_argument("--provider-id", default="spark012-dsv4-layer-pipeline")
	p.add_argument("--model-id", default="deepseek-ai/DeepSeek-V4-Flash")
	p.add_argument("--runtime-id", default="antirez-ds4-3630e64+explicit-preload+stage-handoff+tcp")
	p.add_argument("--quantization-id", default="DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf")
	p.add_argument("--prompt-pattern", required=True, choices=sorted(PROMPT_PATTERNS))
	p.add_argument("--output-token-target", required=True, type=int, choices=sorted(OUTPUT_TARGETS))
	p.add_argument("--prefix-mode", required=True, choices=sorted(PREFIX_MODES))
	p.add_argument("--out", required=True)


def main() -> int:
	ap = argparse.ArgumentParser()
	sub = ap.add_subparsers(dest="cmd", required=True)
	build = sub.add_parser("build-from-stage")
	add_common(build)
	build.add_argument("--stage-handoff", required=True)
	build.add_argument("--parity-artifact", required=True)
	build.add_argument("--prefix-prepare-ms", type=float, default=0.0)
	build.add_argument("--prefix-load-or-fork-ms", type=float, default=0.0)
	build.add_argument("--suffix-tokens-per-row", type=int, default=0)
	build.add_argument("--suffix-prefill-ms", type=float, default=0.0)
	build.add_argument("--output-head-ms", type=float, default=0.0)
	build.add_argument("--production-generation-eligible", action="store_true")
	blocked = sub.add_parser("build-blocked")
	add_common(blocked)
	blocked.add_argument("--parity-artifact-sha256", default="")
	blocked.add_argument("--blocker-kind", required=True)
	blocked.add_argument("--blocker-detail", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	args = ap.parse_args()
	try:
		if args.cmd == "build-from-stage":
			obj = build_from_stage(args)
			errors = validate_artifact(obj)
			if errors:
				raise ValueError("; ".join(errors))
			write_json(Path(args.out), obj)
			print(json.dumps(obj, indent=2, sort_keys=True))
		elif args.cmd == "build-blocked":
			obj = build_blocked(args)
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
