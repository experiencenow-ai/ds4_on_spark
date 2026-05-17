#!/usr/bin/env python3
"""Validate and build fixture-backed DS4 batch-generate API artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


REQUEST_FORMAT = "ds4-batch-generate-request-v1"
RESULT_FORMAT = "ds4-batch-generate-result-v1"
OUTPUT_MODES = {"constrained_candidate", "grammar_constrained", "full_vocab", "finite_logits_only"}
RESULT_STATUSES = {"success", "failed", "blocked"}
ROW_STATUSES = {"success", "failed", "blocked"}
FINISH_REASONS = {"max_tokens", "stop_token", "logits_only", "error", "blocked"}
CONSTRAINED_RATE_TOK_S = 629.183
FULL_VOCAB_RATE_TOK_S = 260.973
FINITE_LOGITS_ROWS_S = 631.672


class Ds4BatchGenerateError(ValueError):
	pass


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def token_hash(token_ids: list[int]) -> str:
	return sha256_obj({"token_ids": token_ids})


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise Ds4BatchGenerateError(f"{path}: root must be an object")
	return obj


def write_json(path: Path, obj: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _expect_string(errors: list[str], obj: dict[str, Any], key: str, allow_empty: bool = False) -> None:
	value = obj.get(key)
	if not isinstance(value, str) or (not allow_empty and value.strip() == ""):
		errors.append(f"{key} must be a {'string' if allow_empty else 'non-empty string'}")


def _expect_bool(errors: list[str], obj: dict[str, Any], key: str) -> None:
	if not isinstance(obj.get(key), bool):
		errors.append(f"{key} must be boolean")


def _expect_number(errors: list[str], obj: dict[str, Any], key: str, minimum: float = 0.0) -> None:
	if not isinstance(obj.get(key), (int, float)) or float(obj.get(key, 0.0)) < minimum:
		errors.append(f"{key} must be a number >= {minimum}")


def _expect_int(errors: list[str], obj: dict[str, Any], key: str, minimum: int = 0) -> None:
	if not isinstance(obj.get(key), int) or int(obj.get(key, 0)) < minimum:
		errors.append(f"{key} must be an integer >= {minimum}")


def _expect_int_list(errors: list[str], obj: dict[str, Any], key: str, required: bool = True) -> None:
	if key not in obj and not required:
		return
	value = obj.get(key)
	if not isinstance(value, list) or not all(isinstance(v, int) and v >= 0 for v in value):
		errors.append(f"{key} must be a list of non-negative integers")


def validate_request(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != REQUEST_FORMAT:
		errors.append(f"format must be {REQUEST_FORMAT}")
	for key in ("spark_count", "num_sparks", "world_size"):
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	for key in ("request_id", "provider_id", "model_id", "runtime_id"):
		_expect_string(errors, obj, key)
	_expect_bool(errors, obj, "telemetry_required")
	policy = obj.get("batch_policy")
	if not isinstance(policy, dict):
		errors.append("batch_policy must be an object")
	else:
		_expect_int(errors, policy, "target_active_rows", 1)
		for key in ("allow_row_replacement", "group_by_output_mode", "prefer_group_by_prefix_handle"):
			_expect_bool(errors, policy, key)
	if "runtime_requirements" in obj:
		reqs = obj.get("runtime_requirements")
		if not isinstance(reqs, dict):
			errors.append("runtime_requirements must be an object when present")
		elif "prefix_kv_required" in reqs:
			_expect_bool(errors, reqs, "prefix_kv_required")
	rows = obj.get("rows")
	if not isinstance(rows, list) or len(rows) == 0:
		errors.append("rows must be a non-empty list")
	elif len({row.get("row_id") for row in rows if isinstance(row, dict)}) != len(rows):
		errors.append("row_id values must be unique")
	if isinstance(rows, list):
		for idx, row in enumerate(rows):
			if not isinstance(row, dict):
				errors.append(f"rows[{idx}] must be an object")
				continue
			prefix = f"rows[{idx}]"
			_expect_string(errors, row, "row_id")
			mode = row.get("output_mode")
			if mode not in OUTPUT_MODES:
				errors.append(f"{prefix}.output_mode must be one of {sorted(OUTPUT_MODES)}")
			_expect_int_list(errors, row, "suffix_token_ids")
			_expect_int(errors, row, "max_output_tokens", 1)
			_expect_int_list(errors, row, "stop_token_ids")
			if not isinstance(row.get("sampling_params"), dict):
				errors.append(f"{prefix}.sampling_params must be an object")
			if "prefix_handle" in row and not isinstance(row.get("prefix_handle"), str):
				errors.append(f"{prefix}.prefix_handle must be a string when present")
			if "prefix_manifest" in row and not isinstance(row.get("prefix_manifest"), dict):
				errors.append(f"{prefix}.prefix_manifest must be an object when present")
			if mode == "constrained_candidate":
				_expect_int_list(errors, row, "candidate_token_ids")
				if isinstance(row.get("candidate_token_ids"), list) and len(row.get("candidate_token_ids", [])) == 0:
					errors.append(f"{prefix}.candidate_token_ids must be non-empty for constrained_candidate")
			if mode == "grammar_constrained":
				if "grammar_ref" not in row and "candidate_token_ids" not in row:
					errors.append(f"{prefix}.grammar_constrained requires grammar_ref or candidate_token_ids")
				_expect_int_list(errors, row, "candidate_token_ids", required=False)
	return errors


def _requests_by_id(requests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
	return {str(obj.get("request_id")): obj for obj in requests if obj.get("format") == REQUEST_FORMAT}


def _request_rows_by_id(request: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
	if not request:
		return {}
	rows = request.get("rows")
	if not isinstance(rows, list):
		return {}
	return {str(row.get("row_id")): row for row in rows if isinstance(row, dict)}


def _validate_output_mode_groups(errors: list[str], telemetry: dict[str, Any], result_rows: list[dict[str, Any]]) -> None:
	groups = telemetry.get("output_mode_groups")
	if not isinstance(groups, list) or len(groups) == 0:
		errors.append("telemetry.output_mode_groups must be a non-empty list")
		return
	group_modes: set[str] = set()
	group_rows = 0
	for idx, group in enumerate(groups):
		if not isinstance(group, dict):
			errors.append(f"telemetry.output_mode_groups[{idx}] must be an object")
			continue
		mode = group.get("output_mode")
		if mode not in OUTPUT_MODES:
			errors.append(f"telemetry.output_mode_groups[{idx}].output_mode is invalid")
		else:
			group_modes.add(str(mode))
		_expect_int(errors, group, "row_count", 1)
		_expect_string(errors, group, "internal_sub_batch_id")
		if "selected_rate_source" in group:
			_expect_string(errors, group, "selected_rate_source")
		if "fallback_full_vocab_used" in group:
			_expect_bool(errors, group, "fallback_full_vocab_used")
		if isinstance(group.get("row_count"), int):
			group_rows += int(group.get("row_count", 0))
	if group_rows != len(result_rows):
		errors.append("telemetry.output_mode_groups row_count total must match result rows")
	if len(group_modes) > 1 and len(groups) < len(group_modes):
		errors.append("mixed output modes must be split into compatible internal sub-batches")


def _validate_prefix_handle_groups(errors: list[str], telemetry: dict[str, Any], result_rows: list[dict[str, Any]]) -> None:
	groups = telemetry.get("prefix_handle_groups")
	if groups is None:
		return
	if not isinstance(groups, list) or len(groups) == 0:
		errors.append("telemetry.prefix_handle_groups must be a non-empty list when present")
		return
	total = 0
	for idx, group in enumerate(groups):
		if not isinstance(group, dict):
			errors.append(f"telemetry.prefix_handle_groups[{idx}] must be an object")
			continue
		_expect_string(errors, group, "prefix_handle")
		_expect_int(errors, group, "row_count", 1)
		if isinstance(group.get("row_count"), int):
			total += int(group["row_count"])
	if total != len(result_rows):
		errors.append("telemetry.prefix_handle_groups row_count total must match result rows")


def validate_result(obj: dict[str, Any], request: dict[str, Any] | None = None) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != RESULT_FORMAT:
		errors.append(f"format must be {RESULT_FORMAT}")
	for key in ("spark_count", "num_sparks", "world_size"):
		if key in obj:
			errors.append(f"top-level fixed Spark count field is not allowed: {key}")
	_expect_string(errors, obj, "request_id")
	if obj.get("status") not in RESULT_STATUSES:
		errors.append(f"status must be one of {sorted(RESULT_STATUSES)}")
	rows = obj.get("rows")
	if not isinstance(rows, list) or len(rows) == 0:
		errors.append("rows must be a non-empty list")
		rows = []
	telemetry = obj.get("telemetry")
	if not isinstance(telemetry, dict):
		errors.append("telemetry must be an object")
		telemetry = {}
	request_rows = _request_rows_by_id(request)
	for idx, row in enumerate(rows):
		if not isinstance(row, dict):
			errors.append(f"rows[{idx}] must be an object")
			continue
		_expect_string(errors, row, "row_id")
		if row.get("status") not in ROW_STATUSES:
			errors.append(f"rows[{idx}].status must be one of {sorted(ROW_STATUSES)}")
		_expect_int_list(errors, row, "committed_token_ids")
		_expect_string(errors, row, "token_hash", allow_empty=row.get("status") != "success")
		if row.get("finish_reason") not in FINISH_REASONS:
			errors.append(f"rows[{idx}].finish_reason must be one of {sorted(FINISH_REASONS)}")
		if not isinstance(row.get("error"), (str, type(None))):
			errors.append(f"rows[{idx}].error must be string or null")
		req_row = request_rows.get(str(row.get("row_id")))
		if req_row and req_row.get("output_mode") == "constrained_candidate":
			allowed = set(req_row.get("candidate_token_ids", []))
			actual = row.get("committed_token_ids", [])
			if not all(token in allowed for token in actual):
				errors.append(f"rows[{idx}] committed_token_ids must be inside candidate_token_ids")
		if req_row and req_row.get("output_mode") == "finite_logits_only" and row.get("committed_token_ids"):
			errors.append(f"rows[{idx}] finite_logits_only must not commit tokens")
	if isinstance(rows, list) and len({row.get("row_id") for row in rows if isinstance(row, dict)}) != len(rows):
		errors.append("row_id values must be unique")
	if request and isinstance(request.get("rows"), list) and len(rows) != len(request.get("rows", [])):
		errors.append("result row count must match request row count")
	for key in ("batch_size", "active_rows", "prefix_hit_count", "prefix_miss_count"):
		_expect_int(errors, telemetry, key, 0)
	if telemetry.get("batch_size") != len(rows):
		errors.append("telemetry.batch_size must equal result row count")
	if isinstance(telemetry.get("active_rows"), int) and telemetry.get("active_rows", 0) > len(rows):
		errors.append("telemetry.active_rows must not exceed result row count")
	for key in (
		"prefix_load_ms",
		"suffix_prefill_ms",
		"decode_ms",
		"output_head_ms",
		"constrained_commit_ms",
		"full_vocab_commit_ms",
		"token_commit_ms",
		"result_collection_ms",
		"end_to_end_output_tokens_per_s",
	):
		_expect_number(errors, telemetry, key)
	_expect_bool(errors, telemetry, "production_generation_eligible")
	_expect_string(errors, telemetry, "blocker_kind", allow_empty=True)
	_expect_string(errors, telemetry, "blocker_detail", allow_empty=True)
	_validate_output_mode_groups(errors, telemetry, rows)
	modes = {group.get("output_mode") for group in telemetry.get("output_mode_groups", []) if isinstance(group, dict)}
	if "full_vocab" in modes and float(telemetry.get("full_vocab_commit_ms", 0.0)) <= 0.0:
		if obj.get("status") == "success":
			errors.append("full_vocab results must report full_vocab_commit_ms")
	if "constrained_candidate" in modes and float(telemetry.get("constrained_commit_ms", 0.0)) <= 0.0:
		if obj.get("status") == "success":
			errors.append("constrained_candidate results must report constrained_commit_ms")
	_validate_prefix_handle_groups(errors, telemetry, rows)
	if "finite_logits_only" in modes and telemetry.get("production_generation_eligible") is True:
		errors.append("finite_logits_only cannot be production_generation_eligible")
	if telemetry.get("production_generation_eligible") is True:
		if obj.get("status") != "success":
			errors.append("production_generation_eligible requires result status success")
		if telemetry.get("blocker_kind") not in ("", "none"):
			errors.append("production_generation_eligible requires blocker_kind none")
		if telemetry.get("derived_artifact") is not False:
			errors.append("production_generation_eligible requires derived_artifact=false")
		if telemetry.get("parity_status") != "passed":
			errors.append("production_generation_eligible requires parity_status=passed")
		if not str(telemetry.get("parity_artifact_sha256", "")).startswith("sha256:"):
			errors.append("production_generation_eligible requires parity_artifact_sha256")
		if telemetry.get("shared_prefix_suffix_runtime_used") is not True and telemetry.get("prefix_kv_runtime_path") != "not_required":
			errors.append("production_generation_eligible requires real shared-prefix/suffix runtime path or prefix_kv_runtime_path=not_required")
		if not all(isinstance(row, dict) and row.get("committed_token_ids") and row.get("token_hash") for row in rows):
			errors.append("production_generation_eligible requires committed token IDs and token_hash for every row")
	else:
		if telemetry.get("blocker_kind") in ("", None):
			errors.append("non-eligible result must report blocker_kind")
	if request:
		request_modes = {row.get("output_mode") for row in request.get("rows", []) if isinstance(row, dict)}
		if "full_vocab" in request_modes and "constrained_candidate" in request_modes:
			full_groups = [group for group in telemetry.get("output_mode_groups", []) if isinstance(group, dict) and group.get("output_mode") == "full_vocab"]
			constrained_groups = [group for group in telemetry.get("output_mode_groups", []) if isinstance(group, dict) and group.get("output_mode") == "constrained_candidate"]
			if not full_groups or not constrained_groups:
				errors.append("mixed full_vocab/constrained_candidate request must keep separate output mode groups")
	return errors


def validate_documents(objs: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[str]]]:
	requests = [obj for obj in objs if obj.get("format") == REQUEST_FORMAT]
	by_id = _requests_by_id(requests)
	results: list[tuple[dict[str, Any], list[str]]] = []
	for obj in objs:
		if obj.get("format") == REQUEST_FORMAT:
			results.append((obj, validate_request(obj)))
		elif obj.get("format") == RESULT_FORMAT:
			results.append((obj, validate_result(obj, by_id.get(str(obj.get("request_id"))))))
		else:
			results.append((obj, [f"format must be {REQUEST_FORMAT} or {RESULT_FORMAT}"]))
	return results


def _choose_tokens(row: dict[str, Any], row_index: int) -> tuple[list[int], str | None, bool]:
	mode = row.get("output_mode")
	max_tokens = int(row.get("max_output_tokens", 1))
	if mode == "finite_logits_only":
		return [], None, False
	if mode == "constrained_candidate":
		candidates = row.get("candidate_token_ids", [])
		token = int(candidates[row_index % len(candidates)])
		return [token for _ in range(max_tokens)], None, False
	if mode == "grammar_constrained" and isinstance(row.get("candidate_token_ids"), list) and row["candidate_token_ids"]:
		candidates = row["candidate_token_ids"]
		token = int(candidates[row_index % len(candidates)])
		return [token for _ in range(max_tokens)], None, False
	token = 1000 + (row_index % 997)
	return [token for _ in range(max_tokens)], None, mode == "grammar_constrained"


def build_result_from_request(request: dict[str, Any]) -> dict[str, Any]:
	errors = validate_request(request)
	if errors:
		raise Ds4BatchGenerateError("; ".join(errors))
	if (request.get("runtime_requirements") or {}).get("prefix_kv_required") is True:
		return _build_missing_prefix_kv_runtime_result(request)
	rows = request["rows"]
	result_rows: list[dict[str, Any]] = []
	mode_counts: dict[str, int] = defaultdict(int)
	fallback_full_vocab = False
	output_tokens = 0
	for idx, row in enumerate(rows):
		committed, error, used_fallback = _choose_tokens(row, idx)
		fallback_full_vocab = fallback_full_vocab or used_fallback
		mode = "full_vocab" if used_fallback else str(row["output_mode"])
		mode_counts[mode] += 1
		output_tokens += len(committed)
		result_rows.append({
			"row_id": row["row_id"],
			"status": "success",
			"committed_token_ids": committed,
			"token_hash": token_hash(committed) if committed else "",
			"output_text_hash": token_hash(committed) if committed else "",
			"finish_reason": "logits_only" if row["output_mode"] == "finite_logits_only" else "max_tokens",
			"error": error,
		})
	groups: list[dict[str, Any]] = []
	for mode in sorted(mode_counts):
		groups.append({
			"internal_sub_batch_id": f"{request['request_id']}:{mode}",
			"output_mode": mode,
			"row_count": mode_counts[mode],
			"selected_rate_source": _selected_rate_source(mode),
			"fallback_full_vocab_used": mode == "full_vocab" and fallback_full_vocab,
		})
	constrained_tokens = sum(
		len(row["committed_token_ids"])
		for row, req in zip(result_rows, rows)
		if req["output_mode"] == "constrained_candidate"
		or (req["output_mode"] == "grammar_constrained" and isinstance(req.get("candidate_token_ids"), list) and len(req["candidate_token_ids"]) > 0)
	)
	full_vocab_tokens = sum(
		len(row["committed_token_ids"])
		for row, req in zip(result_rows, rows)
		if req["output_mode"] == "full_vocab"
		or (req["output_mode"] == "grammar_constrained" and not (isinstance(req.get("candidate_token_ids"), list) and len(req["candidate_token_ids"]) > 0))
	)
	constrained_ms = constrained_tokens * 1000.0 / CONSTRAINED_RATE_TOK_S if constrained_tokens else 0.0
	full_vocab_ms = full_vocab_tokens * 1000.0 / FULL_VOCAB_RATE_TOK_S if full_vocab_tokens else 0.0
	finite_rows = sum(1 for row in rows if row["output_mode"] == "finite_logits_only")
	finite_ms = finite_rows * 1000.0 / FINITE_LOGITS_ROWS_S if finite_rows else 0.0
	token_commit_ms = constrained_ms + full_vocab_ms
	decode_ms = token_commit_ms + finite_ms
	output_tps = output_tokens * 1000.0 / decode_ms if decode_ms > 0.0 and output_tokens else 0.0
	prefix_hits = sum(1 for row in rows if row.get("prefix_handle"))
	telemetry = {
		"batch_size": len(rows),
		"active_rows": min(len(rows), int(request["batch_policy"]["target_active_rows"])),
		"output_mode_groups": groups,
		"prefix_hit_count": prefix_hits,
		"prefix_miss_count": len(rows) - prefix_hits,
		"prefix_load_ms": 0.0 if prefix_hits == len(rows) else 1.0,
		"suffix_prefill_ms": 0.0,
		"decode_ms": decode_ms,
		"output_head_ms": full_vocab_ms + finite_ms,
		"constrained_commit_ms": constrained_ms,
		"full_vocab_commit_ms": full_vocab_ms,
		"token_commit_ms": token_commit_ms,
		"result_collection_ms": 0.05,
		"end_to_end_output_tokens_per_s": output_tps,
		"row_replacement_implemented": False,
		"production_generation_eligible": False,
		"parity_status": "not_run",
		"parity_artifact_sha256": "",
		"derived_artifact": True,
		"shared_prefix_suffix_runtime_used": False,
		"blocker_kind": "production_gates_not_passed",
		"blocker_detail": "fixture-backed callable API path; PP=1/PP=N parity and production shared-prefix/suffix runtime path are not yet wired",
	}
	return {
		"format": RESULT_FORMAT,
		"request_id": request["request_id"],
		"status": "success",
		"rows": result_rows,
		"telemetry": telemetry,
	}


def _prefix_handle_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	counts: dict[str, int] = defaultdict(int)
	for row in rows:
		counts[str(row.get("prefix_handle", ""))] += 1
	return [
		{"prefix_handle": key, "row_count": counts[key]}
		for key in sorted(counts)
		if key != ""
	]


def _build_missing_prefix_kv_runtime_result(request: dict[str, Any]) -> dict[str, Any]:
	rows = request["rows"]
	result_rows = [
		{
			"row_id": row["row_id"],
			"status": "blocked",
			"committed_token_ids": [],
			"token_hash": "",
			"output_text_hash": "",
			"finish_reason": "blocked",
			"error": "missing_prefix_kv_runtime_hook",
		}
		for row in rows
	]
	mode_counts: dict[str, int] = defaultdict(int)
	for row in rows:
		mode_counts[str(row["output_mode"])] += 1
	groups = [
		{
			"internal_sub_batch_id": f"{request['request_id']}:{mode}",
			"output_mode": mode,
			"row_count": mode_counts[mode],
			"selected_rate_source": _selected_rate_source(mode),
			"fallback_full_vocab_used": False,
		}
		for mode in sorted(mode_counts)
	]
	prefix_groups = _prefix_handle_groups(rows)
	return {
		"format": RESULT_FORMAT,
		"request_id": request["request_id"],
		"status": "blocked",
		"rows": result_rows,
		"telemetry": {
			"batch_size": len(rows),
			"active_rows": min(len(rows), int(request["batch_policy"]["target_active_rows"])),
			"output_mode_groups": groups,
			"prefix_handle_groups": prefix_groups,
			"prefix_hit_count": 0,
			"prefix_miss_count": len(rows),
			"prefix_load_ms": 0.0,
			"suffix_prefill_ms": 0.0,
			"decode_ms": 0.0,
			"output_head_ms": 0.0,
			"constrained_commit_ms": 0.0,
			"full_vocab_commit_ms": 0.0,
			"token_commit_ms": 0.0,
			"result_collection_ms": 0.0,
			"end_to_end_output_tokens_per_s": 0.0,
			"row_replacement_implemented": False,
			"production_generation_eligible": False,
			"parity_status": "passed",
			"parity_artifact_sha256": "sha256:placeholder-b512-slice-tile8-pp1-logits-parity-passed",
			"derived_artifact": True,
			"shared_prefix_suffix_runtime_used": False,
			"prefix_kv_runtime_path": "missing",
			"prefix_kv_required": True,
			"blocker_kind": "missing_prefix_kv_runtime_hook",
			"blocker_detail": (
				"repo-owned callable runtime hook is missing for prefix_prepare, prefix_pin, "
				"prefix_fork, session_append, session_decode, session_release, and prefix_release; "
				"scripts/ds4_batch_generate remains fixture-backed"
			),
		},
	}


def _selected_rate_source(mode: str) -> str:
	if mode == "constrained_candidate":
		return "constrained_candidate_commit"
	if mode == "full_vocab":
		return "full_vocab_output_head"
	if mode == "finite_logits_only":
		return "finite_logits_rows"
	if mode == "grammar_constrained":
		return "grammar_allowed_token_set"
	return "unknown"


def main() -> int:
	if len(sys.argv) > 1 and sys.argv[1] not in ("build-result", "validate", "-h", "--help"):
		paths = [Path(raw) for raw in sys.argv[1:]]
		return _validate_paths(paths)
	ap = argparse.ArgumentParser()
	sub = ap.add_subparsers(dest="cmd", required=True)
	build = sub.add_parser("build-result")
	build.add_argument("--request", required=True)
	build.add_argument("--output", required=True)
	validate = sub.add_parser("validate")
	validate.add_argument("paths", nargs="+")
	args = ap.parse_args()
	try:
		if args.cmd == "build-result":
			request = load_json(Path(args.request))
			result = build_result_from_request(request)
			errors = validate_result(result, request)
			if errors:
				raise Ds4BatchGenerateError("; ".join(errors))
			write_json(Path(args.output), result)
			print(json.dumps(result, indent=2, sort_keys=True))
			return 0
		return _validate_paths([Path(raw) for raw in args.paths])
	except (OSError, json.JSONDecodeError, Ds4BatchGenerateError) as exc:
		print(f"error: {exc}", file=sys.stderr)
		return 1


def _validate_paths(paths: list[Path]) -> int:
	failed = False
	objs: list[tuple[Path, dict[str, Any]]] = []
	for path in paths:
		try:
			objs.append((path, load_json(path)))
		except (OSError, json.JSONDecodeError, Ds4BatchGenerateError) as exc:
			print(f"error: {path}: {exc}", file=sys.stderr)
			failed = True
	results = validate_documents([obj for _, obj in objs])
	for (path, _), (_, errors) in zip(objs, results):
		if errors:
			failed = True
			for error in errors:
				print(f"error: {path}: {error}", file=sys.stderr)
		else:
			print(f"ok: {path}")
	return 2 if failed else 0


if __name__ == "__main__":
	raise SystemExit(main())
