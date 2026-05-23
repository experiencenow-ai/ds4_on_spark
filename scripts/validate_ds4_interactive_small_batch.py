#!/usr/bin/env python3
"""Build and validate DS4 small-batch interactive full-vocab artifacts."""

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


FORMAT = "ds4-interactive-small-batch-benchmark-v1"
OUTPUT_MODES = {"full_vocab"}
PROMPT_SHAPES = {"independent_rows", "single_combined_prompt_control"}


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_file(path: Path) -> str:
	return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def max_number(values: Any) -> float:
	if not isinstance(values, list):
		return 0.0
	nums = [float(v) for v in values if isinstance(v, (int, float))]
	return max(nums) if nums else 0.0


def nested_last_ms(stage: dict[str, Any]) -> float:
	finish = stage.get("streaming_schedule_finish_ms")
	if isinstance(finish, list) and finish and isinstance(finish[-1], list) and finish[-1]:
		return float(finish[-1][-1])
	value = stage.get("actual_end_to_end_rows_per_s_if_measured", stage.get("achieved_streaming_rows_per_s", 0.0))
	batch = int(stage.get("batch_size", 0))
	mb = int(stage.get("microbatch_count", 1))
	if isinstance(value, (int, float)) and float(value) > 0.0 and batch > 0:
		return batch * mb * 1000.0 / float(value)
	return 0.0


def build_from_stage(args: argparse.Namespace) -> dict[str, Any]:
	stage_path = Path(args.stage_handoff)
	stage = load_json(stage_path)
	profile = stage.get("token_commit_profile", {})
	if not isinstance(profile, dict):
		profile = {}
	batch = int(stage.get("batch_size", 0))
	row_count = int(args.row_count) if args.row_count > 0 else batch
	wall_ms = float(args.end_to_end_wall_ms) if args.end_to_end_wall_ms > 0.0 else nested_last_ms(stage)
	output_tokens = row_count * int(args.output_token_target)
	stage_blocker = str(stage.get("blocker_kind", "none") or "none")
	finite_output = bool(stage.get("final_output_finite"))
	committed_ids = bool(stage.get("committed_token_ids_present"))
	token_hash = str(stage.get("token_hash", "") or "")
	if stage_blocker != "none":
		blocker_kind = stage_blocker
		blocker_detail = str(stage.get("blocker_detail", "stage handoff failed") or "stage handoff failed")
	elif finite_output is not True:
		blocker_kind = "nonfinite_final_output"
		blocker_detail = "stage handoff did not produce finite final logits"
	elif committed_ids is not True or not token_hash.startswith("fnv64:"):
		blocker_kind = "missing_full_vocab_token_commit"
		blocker_detail = "stage handoff produced logits but no committed full-vocab token IDs/hash"
	else:
		blocker_kind = "none"
		blocker_detail = ""
	success = blocker_kind == "none"
	aggregate_tps = (output_tokens * 1000.0 / wall_ms) if success and wall_ms > 0.0 else 0.0
	baseline_tps = float(args.baseline_aggregate_tok_s)
	obj: dict[str, Any] = {
		"format": FORMAT,
		"run_id": args.run_id,
		"model_id": str(stage.get("model_id", "")),
		"runtime_id": str(stage.get("runtime_id", "")),
		"quantization_id": str(stage.get("quantization_id", "")),
		"optimized_kernel_flags": dict(stage.get("stage_env", {})),
		"output_mode": "full_vocab",
		"batch_size": batch,
		"row_count": row_count,
		"logical_question_count": int(args.logical_question_count),
		"prompt_shape": args.prompt_shape,
		"prompt_tokens_per_row": int(args.prompt_tokens_per_row),
		"output_token_target": int(args.output_token_target),
		"max_output_tokens": int(args.max_output_tokens),
		"decode_steps": int(args.output_token_target),
		"full_vocab_output_head_ms": max_number(profile.get("output_head_ms")),
		"token_commit_ms": float(stage.get("token_commit_ms", max_number(stage.get("token_commit_ms_by_microbatch")))),
		"result_collection_ms": max_number(profile.get("result_collection_ms")),
		"end_to_end_wall_ms": wall_ms,
		"aggregate_output_tokens_per_s": aggregate_tps,
		"per_row_output_tokens_per_s": (aggregate_tps / row_count) if row_count > 0 else 0.0,
		"speedup_vs_b1": (aggregate_tps / baseline_tps) if baseline_tps > 0.0 else 1.0,
		"time_to_first_token_ms": wall_ms,
		"time_to_all_rows_complete_ms": wall_ms,
		"committed_token_ids_present": committed_ids,
		"token_hash": token_hash if token_hash != "" else "not_available",
		"finite_output": finite_output,
		"blocker_kind": blocker_kind,
		"blocker_detail": blocker_detail,
		"source_stage_handoff_artifact": str(stage_path),
		"source_stage_handoff_artifact_sha256": str(stage.get("artifact_sha256", "")) or sha256_file(stage_path),
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


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	for key in ("format", "run_id", "model_id", "runtime_id", "quantization_id", "output_mode", "prompt_shape", "token_hash", "blocker_kind", "artifact_sha256", "artifact_hash"):
		expect_string(errors, obj, key)
	if obj.get("format") != FORMAT:
		errors.append(f"format must be {FORMAT}")
	if obj.get("artifact_sha256") != artifact_sha256(obj):
		errors.append("artifact_sha256 does not match canonical artifact body")
	if obj.get("artifact_hash") != obj.get("artifact_sha256"):
		errors.append("artifact_hash must match artifact_sha256")
	if obj.get("output_mode") not in OUTPUT_MODES:
		errors.append("output_mode must be full_vocab")
	if obj.get("prompt_shape") not in PROMPT_SHAPES:
		errors.append("prompt_shape is invalid")
	for key in ("batch_size", "row_count", "prompt_tokens_per_row", "output_token_target", "max_output_tokens", "decode_steps"):
		if not isinstance(obj.get(key), int) or int(obj.get(key, 0)) <= 0:
			errors.append(f"{key} must be positive integer")
	for key in ("full_vocab_output_head_ms", "token_commit_ms", "result_collection_ms", "end_to_end_wall_ms", "aggregate_output_tokens_per_s", "per_row_output_tokens_per_s", "time_to_first_token_ms", "time_to_all_rows_complete_ms"):
		expect_number(errors, obj, key)
	if not isinstance(obj.get("speedup_vs_b1"), (int, float)) or float(obj.get("speedup_vs_b1", 0.0)) < 0.0:
		errors.append("speedup_vs_b1 must be non-negative")
	for key in ("committed_token_ids_present", "finite_output"):
		if not isinstance(obj.get(key), bool):
			errors.append(f"{key} must be boolean")
	if obj.get("prompt_shape") == "independent_rows":
		if obj.get("row_count") != obj.get("batch_size"):
			errors.append("independent_rows requires row_count=batch_size")
	else:
		if obj.get("batch_size") != 1:
			errors.append("single_combined_prompt_control must be explicit B=1 shape")
		if obj.get("row_count") != 1:
			errors.append("single_combined_prompt_control requires row_count=1")
		if int(obj.get("logical_question_count", 0)) <= 1:
			errors.append("single_combined_prompt_control requires logical_question_count > 1")
	if obj.get("blocker_kind") == "none":
		if obj.get("finite_output") is not True:
			errors.append("successful artifact requires finite_output=true")
		if obj.get("committed_token_ids_present") is not True:
			errors.append("successful artifact requires committed token ids")
		if not str(obj.get("token_hash", "")).startswith("fnv64:"):
			errors.append("successful artifact requires fnv64 token_hash")
		if float(obj.get("aggregate_output_tokens_per_s", 0.0)) <= 0.0:
			errors.append("successful artifact requires positive aggregate tok/s")
		if float(obj.get("time_to_first_token_ms", 0.0)) <= 0.0:
			errors.append("successful artifact requires time_to_first_token_ms")
		if float(obj.get("speedup_vs_b1", 0.0)) <= 0.0:
			errors.append("successful artifact requires positive speedup_vs_b1")
	else:
		if not isinstance(obj.get("blocker_detail"), str) or obj.get("blocker_detail", "").strip() == "":
			errors.append("blocked artifact requires blocker_detail")
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
	build.add_argument("--stage-handoff", required=True)
	build.add_argument("--prompt-shape", choices=sorted(PROMPT_SHAPES), required=True)
	build.add_argument("--row-count", type=int, default=0)
	build.add_argument("--logical-question-count", type=int, default=1)
	build.add_argument("--prompt-tokens-per-row", type=int, default=1)
	build.add_argument("--output-token-target", type=int, default=1)
	build.add_argument("--max-output-tokens", type=int, default=1)
	build.add_argument("--baseline-aggregate-tok-s", type=float, default=0.0)
	build.add_argument("--end-to-end-wall-ms", type=float, default=0.0)
	build.add_argument("--out", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	args = ap.parse_args()
	try:
		if args.cmd == "build":
			obj = build_from_stage(args)
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
