#!/usr/bin/env python3
"""Build and validate DS4 constrained candidate-set-size sweep artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

try:
	from scripts._lib.json_utils import artifact_sha256
	from scripts._lib.json_utils import load_json
except ImportError:
	from _lib.json_utils import artifact_sha256
	from _lib.json_utils import load_json


FORMAT = "ds4-constrained-candidate-sweep-v1"
MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"
RUNTIME_ID = "antirez-ds4-3630e64+explicit-preload+stage-handoff+tcp"
QUANT_ID = "DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf"
PROVIDER_ID = "spark012-dsv4-layer-pipeline"
PROMPT_PATTERN = "shared_prefix_compact_suffix"
REQUEST_SHAPE = "b512_separate_rows"
CONSTRAINED_KINDS = {"numeric_ids", "digits_spaces_newline", "explicit_token_set", "synthetic_candidate_set"}
CANDIDATE_KINDS = CONSTRAINED_KINDS | {"full_vocab_control"}
PREFIX_MODES = {"hit_fork", "miss_prepare"}


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_file(path: Path) -> str:
	return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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
			raise ValueError("token ids must be non-negative")
		out.append(value)
	return out


def nested_last_ms(stage: dict[str, Any]) -> float:
	finish = stage.get("streaming_schedule_finish_ms")
	if isinstance(finish, list) and len(finish) > 0 and isinstance(finish[-1], list) and len(finish[-1]) > 0:
		return float(finish[-1][-1])
	achieved = float(stage.get("achieved_streaming_rows_per_s", 0.0))
	batch = int(stage.get("batch_size", 0))
	mb = int(stage.get("microbatch_count", 0))
	if achieved > 0.0 and batch > 0 and mb > 0:
		return (batch * mb * 1000.0 / achieved)
	return 0.0


def stage_candidate_ids(stage: dict[str, Any]) -> list[int]:
	env = stage.get("stage_env")
	if isinstance(env, dict):
		items = parse_i32_csv(str(env.get("DS4_CUDA_STACK_PROBE_CONSTRAINED_TOKEN_IDS", "")))
		if items:
			return items
	items = stage.get("constrained_token_ids")
	if isinstance(items, list) and len(items) > 0:
		return [int(v) for v in items]
	return []


def reported_candidate_ids(stage: dict[str, Any]) -> list[int]:
	items = stage.get("constrained_token_ids")
	if isinstance(items, list) and len(items) > 0:
		return [int(v) for v in items]
	return []


def stage_uint(stage: dict[str, Any], key: str, default: int) -> int:
	value = stage.get(key, default)
	try:
		value_int = int(value)
	except (TypeError, ValueError):
		return default
	return value_int if value_int >= 0 else default


def committed_ids(stage: dict[str, Any]) -> list[int]:
	items = stage.get("committed_token_ids")
	if not isinstance(items, list):
		return []
	return [int(v) for v in items if isinstance(v, int)]


def common_from_stage(stage: dict[str, Any]) -> dict[str, Any]:
	env = dict(stage.get("stage_env", {}))
	shared_flags = {
		key: str(env[key])
		for key in ("DS4_CUDA_MOE_SLICE_TILE8", "DS4_CUDA_STACK_PROBE_BATCH_HEAD")
		if key in env
	}
	return {
		"provider_id": str(stage.get("provider_id", PROVIDER_ID)) if stage.get("provider_id") else PROVIDER_ID,
		"model_id": str(stage.get("model_id", MODEL_ID)),
		"runtime_id": str(stage.get("runtime_id", RUNTIME_ID)),
		"quantization_id": str(stage.get("quantization_id", QUANT_ID)),
		"optimized_kernel_flags": shared_flags,
		"batch_size": int(stage.get("batch_size", 0)),
		"microbatch_count": int(stage.get("microbatch_count", 0)),
	}


def build_result_from_stage(path: Path, kind: str, count: int, suffix_tokens: int) -> dict[str, Any]:
	stage = load_json(path)
	candidate_ids = stage_candidate_ids(stage)
	reported_ids = reported_candidate_ids(stage)
	if count != len(candidate_ids):
		raise ValueError(f"{path}: candidate count {count} does not match {len(candidate_ids)} stage ids")
	commit_ms = float(stage.get("token_commit_ms", 0.0))
	wall_ms = nested_last_ms(stage)
	total_ms = wall_ms + commit_ms
	output_tokens = int(stage.get("batch_size", 0)) * int(stage.get("microbatch_count", 0))
	tokens = committed_ids(stage)
	candidate_set = set(candidate_ids)
	blocker_kind = str(stage.get("blocker_kind", "none"))
	blocker_detail = str(stage.get("blocker_detail", ""))
	runtime_requested_count = stage_uint(stage, "constrained_token_count_requested", len(candidate_ids))
	runtime_enforced_count = stage_uint(stage, "constrained_token_count_enforced", len(reported_ids) if reported_ids else 0)
	if blocker_kind == "none" and runtime_enforced_count == 0 and reported_ids:
		runtime_enforced_count = len(reported_ids)
	if blocker_kind == "none" and runtime_requested_count != len(candidate_ids):
		blocker_kind = "runtime_candidate_set_mismatch"
		blocker_detail = f"requested {len(candidate_ids)} candidate tokens, but runtime recorded requested count {runtime_requested_count}"
	if reported_ids and len(reported_ids) != len(candidate_ids) and blocker_kind == "none":
		blocker_kind = "runtime_candidate_set_truncated"
		blocker_detail = f"requested {len(candidate_ids)} candidate tokens, but stage artifact reported {len(reported_ids)} active constrained_token_ids; do not count this as a validated {len(candidate_ids)}-candidate runtime-enforced set"
	if blocker_kind == "none" and runtime_enforced_count != len(candidate_ids):
		blocker_kind = "runtime_candidate_set_truncated"
		blocker_detail = f"requested {len(candidate_ids)} candidate tokens, but runtime enforced {runtime_enforced_count}"
	success = blocker_kind == "none"
	row = {
		"candidate_vocabulary_kind": kind,
		"candidate_token_count": count,
		"candidate_token_ids_hash": sha256_obj(candidate_ids),
		"output_token_target": 1,
		"prefix_mode": "hit_fork",
		"suffix_tokens_per_row": suffix_tokens,
		"decode_ms": 0.0,
		"constrained_commit_ms": commit_ms if success else 0.0,
		"result_collection_ms": commit_ms if success else 0.0,
		"end_to_end_output_tokens_per_s": (output_tokens * 1000.0 / total_ms) if success and total_ms > 0.0 else 0.0,
		"committed_token_ids_present": bool(stage.get("committed_token_ids_present")) if success else False,
		"token_hash": str(stage.get("token_hash", "")) if success else "not_available",
		"all_committed_tokens_in_candidate_set": bool(tokens) and all(v in candidate_set for v in tokens) if success else False,
		"fallback_full_vocab_used": False,
		"finite_output": bool(stage.get("final_output_finite")) if success else False,
		"parity_artifact_sha256": "",
		"production_generation_eligible": False,
		"blocker_kind": blocker_kind,
		"blocker_detail": blocker_detail,
		"source_artifact": str(path),
		"source_artifact_sha256": str(stage.get("artifact_sha256", "")) or sha256_file(path),
		"runtime_requested_candidate_token_count": runtime_requested_count,
		"runtime_enforced_candidate_token_count": runtime_enforced_count,
		"runtime_reported_candidate_token_count": len(reported_ids),
		"runtime_reported_candidate_token_ids_hash": sha256_obj(reported_ids) if reported_ids else "",
		"candidate_set_fully_reported": len(reported_ids) == len(candidate_ids),
	}
	row["candidate_token_ids"] = candidate_ids
	return row


def build_result_from_control(path: Path) -> dict[str, Any]:
	obj = load_json(path)
	return {
		"candidate_vocabulary_kind": "full_vocab_control",
		"candidate_token_count": 0,
		"candidate_token_ids_hash": "",
		"output_token_target": int(obj.get("output_token_target", 1)),
		"prefix_mode": str(obj.get("prefix_mode", "hit_fork")),
		"suffix_tokens_per_row": int(obj.get("suffix_tokens_per_row", 0)),
		"decode_ms": float(obj.get("decode_ms", 0.0)),
		"constrained_commit_ms": 0.0,
		"result_collection_ms": float(obj.get("full_vocab_commit_ms", obj.get("result_collection_ms", 0.0))),
		"end_to_end_output_tokens_per_s": float(obj.get("end_to_end_output_tokens_per_s", 0.0)),
		"committed_token_ids_present": bool(obj.get("committed_token_ids_present")),
		"token_hash": str(obj.get("token_hash", "")),
		"all_committed_tokens_in_candidate_set": False,
		"fallback_full_vocab_used": True,
		"finite_output": bool(obj.get("finite_output")),
		"parity_artifact_sha256": str(obj.get("parity_artifact_sha256", "")),
		"production_generation_eligible": False,
		"blocker_kind": str(obj.get("blocker_kind", "none")),
		"blocker_detail": str(obj.get("blocker_detail", "")),
		"source_artifact": str(path),
		"source_artifact_sha256": str(obj.get("artifact_sha256", "")) or sha256_file(path),
	}


def threshold(results: list[dict[str, Any]], cutoff: float) -> int:
	counts = [
		int(row["candidate_token_count"])
		for row in results
		if row.get("candidate_vocabulary_kind") != "full_vocab_control"
		and row.get("blocker_kind") == "none"
		and float(row.get("end_to_end_output_tokens_per_s", 0.0)) >= cutoff
	]
	return max(counts) if counts else 0


def first_below(results: list[dict[str, Any]], cutoff: float) -> int | None:
	rows = sorted(
		(row for row in results if row.get("candidate_vocabulary_kind") != "full_vocab_control"),
		key=lambda row: int(row.get("candidate_token_count", 0)),
	)
	for row in rows:
		if float(row.get("end_to_end_output_tokens_per_s", 0.0)) < cutoff:
			return int(row.get("candidate_token_count", 0))
	return None


def first_blocked(results: list[dict[str, Any]]) -> int | None:
	rows = sorted(
		(row for row in results if row.get("candidate_vocabulary_kind") != "full_vocab_control"),
		key=lambda row: int(row.get("candidate_token_count", 0)),
	)
	for row in rows:
		if row.get("blocker_kind") != "none":
			return int(row.get("candidate_token_count", 0))
	return None


def classify_regression(results: list[dict[str, Any]]) -> str:
	below = first_below(results, 500.0)
	if below is None:
		blocked = first_blocked(results)
		if blocked is not None:
			row = next(item for item in results if int(item.get("candidate_token_count", -1)) == blocked)
			return str(row.get("blocker_kind", "blocked"))
		return "not_observed"
	row = next(item for item in results if int(item.get("candidate_token_count", -1)) == below)
	if row.get("fallback_full_vocab_used") is True:
		return "fallback_full_vocab"
	if row.get("blocker_kind") != "none":
		return str(row.get("blocker_kind", "blocked"))
	if float(row.get("constrained_commit_ms", 0.0)) >= float(row.get("result_collection_ms", 0.0)):
		return "commit_scoring"
	return "result_collection"


def build_sweep(args: argparse.Namespace) -> dict[str, Any]:
	results: list[dict[str, Any]] = []
	common: dict[str, Any] = {}
	for raw in args.stage_artifact:
		parts = raw.split(":", 2)
		if len(parts) != 3:
			raise ValueError("--stage-artifact must be COUNT:KIND:PATH")
		count = int(parts[0])
		kind = parts[1]
		if kind not in CONSTRAINED_KINDS:
			raise ValueError(f"{kind}: constrained stage kind is invalid")
		path = Path(parts[2])
		row = build_result_from_stage(path, kind, count, int(args.suffix_tokens_per_row))
		results.append(row)
		if not common:
			common = common_from_stage(load_json(path))
	if args.full_vocab_control:
		results.append(build_result_from_control(Path(args.full_vocab_control)))
	if not common:
		common = {
			"provider_id": PROVIDER_ID,
			"model_id": MODEL_ID,
			"runtime_id": RUNTIME_ID,
			"quantization_id": QUANT_ID,
			"optimized_kernel_flags": {},
			"batch_size": 512,
			"microbatch_count": 16,
		}
	results.sort(key=lambda row: (999999 if row.get("candidate_vocabulary_kind") == "full_vocab_control" else int(row["candidate_token_count"])))
	parity_sha = str(args.parity_artifact_sha256)
	for row in results:
		if not row.get("parity_artifact_sha256"):
			row["parity_artifact_sha256"] = parity_sha
	obj: dict[str, Any] = {
		"format": FORMAT,
		"run_id": args.run_id,
		"provider_id": common["provider_id"],
		"model_id": common["model_id"],
		"runtime_id": common["runtime_id"],
		"quantization_id": common["quantization_id"],
		"optimized_kernel_flags": common["optimized_kernel_flags"],
		"batch_size": common["batch_size"],
		"microbatch_count": common["microbatch_count"],
		"prompt_pattern": PROMPT_PATTERN,
		"request_shape": REQUEST_SHAPE,
		"sweep_results": results,
		"largest_candidate_token_count_above_600_tok_s": threshold(results, 600.0),
		"largest_candidate_token_count_above_500_tok_s": threshold(results, 500.0),
		"first_candidate_token_count_below_500_tok_s": first_below(results, 500.0),
		"first_unproven_candidate_token_count": first_blocked(results),
		"regression_component": classify_regression(results),
		"production_generation_eligible": False,
		"production_eligibility_detail": "candidate sweep uses row-token suffix probe or derived artifacts; production requires shared_prefix_hit_fork_runtime",
	}
	obj["artifact_sha256"] = artifact_sha256(obj)
	obj["artifact_hash"] = obj["artifact_sha256"]
	return obj


def expect_string(errors: list[str], obj: dict[str, Any], key: str) -> None:
	if not isinstance(obj.get(key), str) or obj.get(key, "").strip() == "":
		errors.append(f"{key} must be a non-empty string")


def expect_number(errors: list[str], obj: dict[str, Any], key: str, minimum: float = 0.0) -> None:
	if not isinstance(obj.get(key), (int, float)) or float(obj.get(key, 0.0)) < minimum:
		errors.append(f"{key} must be a number >= {minimum}")


def validate_row(row: dict[str, Any], index: int) -> list[str]:
	errors: list[str] = []
	prefix = f"sweep_results[{index}]"
	for key in ("candidate_vocabulary_kind", "prefix_mode", "token_hash", "parity_artifact_sha256", "blocker_kind"):
		if not isinstance(row.get(key), str) or row.get(key, "").strip() == "":
			errors.append(f"{prefix}.{key} must be a non-empty string")
	if row.get("candidate_vocabulary_kind") not in CANDIDATE_KINDS:
		errors.append(f"{prefix}.candidate_vocabulary_kind is invalid")
	if row.get("prefix_mode") not in PREFIX_MODES:
		errors.append(f"{prefix}.prefix_mode is invalid")
	if row.get("output_token_target") != 1:
		errors.append(f"{prefix}.output_token_target must be 1")
	for key in ("decode_ms", "constrained_commit_ms", "result_collection_ms", "end_to_end_output_tokens_per_s"):
		if not isinstance(row.get(key), (int, float)) or float(row.get(key, 0.0)) < 0.0:
			errors.append(f"{prefix}.{key} must be a non-negative number")
	for key in ("committed_token_ids_present", "all_committed_tokens_in_candidate_set", "fallback_full_vocab_used", "finite_output", "production_generation_eligible"):
		if not isinstance(row.get(key), bool):
			errors.append(f"{prefix}.{key} must be boolean")
	if "candidate_set_fully_reported" in row and not isinstance(row.get("candidate_set_fully_reported"), bool):
		errors.append(f"{prefix}.candidate_set_fully_reported must be boolean")
	count = row.get("candidate_token_count")
	if not isinstance(count, int) or count < 0:
		errors.append(f"{prefix}.candidate_token_count must be non-negative integer")
	if row.get("candidate_vocabulary_kind") == "full_vocab_control":
		if count != 0:
			errors.append(f"{prefix}.full_vocab_control must have candidate_token_count=0")
		if row.get("fallback_full_vocab_used") is not True:
			errors.append(f"{prefix}.full_vocab_control must set fallback_full_vocab_used")
		if row.get("all_committed_tokens_in_candidate_set") is not False:
			errors.append(f"{prefix}.full_vocab_control must not claim candidate-set containment")
	else:
		if count <= 0:
			errors.append(f"{prefix}.constrained row requires candidate_token_count > 0")
		if not str(row.get("candidate_token_ids_hash", "")).startswith("sha256:"):
			errors.append(f"{prefix}.candidate_token_ids_hash must be sha256")
		if "runtime_reported_candidate_token_count" in row:
			if not isinstance(row.get("runtime_reported_candidate_token_count"), int) or int(row.get("runtime_reported_candidate_token_count", -1)) < 0:
				errors.append(f"{prefix}.runtime_reported_candidate_token_count must be non-negative integer")
		for runtime_key in ("runtime_requested_candidate_token_count", "runtime_enforced_candidate_token_count"):
			if runtime_key in row:
				if not isinstance(row.get(runtime_key), int) or int(row.get(runtime_key, -1)) < 0:
					errors.append(f"{prefix}.{runtime_key} must be non-negative integer")
		if row.get("blocker_kind") == "runtime_candidate_set_truncated" and row.get("candidate_set_fully_reported") is not False:
			errors.append(f"{prefix}.runtime_candidate_set_truncated requires candidate_set_fully_reported=false")
		if row.get("fallback_full_vocab_used") is not False:
			errors.append(f"{prefix}.constrained row must not use full-vocab fallback")
		if row.get("blocker_kind") == "none":
			if row.get("all_committed_tokens_in_candidate_set") is not True:
				errors.append(f"{prefix}.constrained row must keep all committed tokens in candidate set")
			if float(row.get("constrained_commit_ms", 0.0)) <= 0.0:
				errors.append(f"{prefix}.constrained row requires constrained_commit_ms")
			if row.get("candidate_set_fully_reported") is not True:
				errors.append(f"{prefix}.successful constrained row must fully report the runtime candidate set")
			if row.get("runtime_reported_candidate_token_count") != count:
				errors.append(f"{prefix}.successful constrained row must report all {count} runtime candidate tokens")
			if row.get("runtime_requested_candidate_token_count") != count:
				errors.append(f"{prefix}.successful constrained row must record requested candidate count {count}")
			if row.get("runtime_enforced_candidate_token_count") != count:
				errors.append(f"{prefix}.successful constrained row must enforce candidate count {count}")
	if row.get("blocker_kind") == "none":
		if row.get("finite_output") is not True:
			errors.append(f"{prefix}.successful row requires finite_output")
		if row.get("committed_token_ids_present") is not True:
			errors.append(f"{prefix}.successful row requires committed token ids")
		if not str(row.get("token_hash", "")).startswith("fnv64:"):
			errors.append(f"{prefix}.successful row requires fnv64 token_hash")
		if float(row.get("end_to_end_output_tokens_per_s", 0.0)) <= 0.0:
			errors.append(f"{prefix}.successful row requires positive tokens/s")
	elif not isinstance(row.get("blocker_detail"), str) or row.get("blocker_detail", "").strip() == "":
		errors.append(f"{prefix}.blocked row requires blocker_detail")
	if row.get("production_generation_eligible") is True:
		errors.append(f"{prefix}.sweep rows must not claim production_generation_eligible")
	return errors


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in ("format", "run_id", "provider_id", "model_id", "runtime_id", "quantization_id", "prompt_pattern", "request_shape", "artifact_sha256", "artifact_hash"):
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
	if obj.get("prompt_pattern") != PROMPT_PATTERN:
		errors.append(f"prompt_pattern must be {PROMPT_PATTERN}")
	if obj.get("request_shape") != REQUEST_SHAPE:
		errors.append(f"request_shape must be {REQUEST_SHAPE}")
	if not isinstance(obj.get("optimized_kernel_flags"), dict):
		errors.append("optimized_kernel_flags must be an object")
	if obj.get("production_generation_eligible") is not False:
		errors.append("candidate sweep summary must not claim production_generation_eligible")
	rows = obj.get("sweep_results")
	if not isinstance(rows, list) or len(rows) == 0:
		errors.append("sweep_results must be a non-empty list")
	else:
		seen: set[int] = set()
		for idx,row in enumerate(rows):
			if not isinstance(row, dict):
				errors.append(f"sweep_results[{idx}] must be object")
				continue
			errors.extend(validate_row(row, idx))
			if row.get("candidate_vocabulary_kind") != "full_vocab_control":
				count = int(row.get("candidate_token_count", -1))
				if count in seen:
					errors.append(f"sweep_results[{idx}].candidate_token_count is duplicated")
				seen.add(count)
		for needed in (15, 32, 64, 128, 256, 512, 1024, 2048):
			if needed not in seen:
				errors.append(f"missing constrained candidate count {needed}")
		if not any(row.get("candidate_vocabulary_kind") == "full_vocab_control" for row in rows if isinstance(row, dict)):
			errors.append("missing full_vocab_control row")
		if obj.get("largest_candidate_token_count_above_600_tok_s") != threshold(rows, 600.0):
			errors.append("largest_candidate_token_count_above_600_tok_s is wrong")
		if obj.get("largest_candidate_token_count_above_500_tok_s") != threshold(rows, 500.0):
			errors.append("largest_candidate_token_count_above_500_tok_s is wrong")
		if obj.get("first_candidate_token_count_below_500_tok_s") != first_below(rows, 500.0):
			errors.append("first_candidate_token_count_below_500_tok_s is wrong")
		if obj.get("first_unproven_candidate_token_count") != first_blocked(rows):
			errors.append("first_unproven_candidate_token_count is wrong")
		if obj.get("regression_component") != classify_regression(rows):
			errors.append("regression_component is wrong")
	return errors


def main() -> int:
	if len(sys.argv) > 1 and sys.argv[1] not in ("build", "validate", "-h", "--help"):
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
	build = sub.add_parser("build")
	build.add_argument("--run-id", required=True)
	build.add_argument("--stage-artifact", action="append", default=[], help="COUNT:KIND:PATH for constrained stage summary artifacts.")
	build.add_argument("--full-vocab-control", default="")
	build.add_argument("--suffix-tokens-per-row", type=int, default=1)
	build.add_argument("--parity-artifact-sha256", required=True)
	build.add_argument("--out", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	args = ap.parse_args()
	try:
		if args.cmd == "build":
			obj = build_sweep(args)
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
