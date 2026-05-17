#!/usr/bin/env python3
"""Validate DS4 prefix/KV cache and session live-smoke artifacts."""

from __future__ import annotations

import json
import sys
from argparse import ArgumentParser
from pathlib import Path
from typing import Any


PREFIX_MANIFEST_FORMAT = "ds4-prefix-manifest-v1"
PREFIX_CACHE_STATUS_FORMAT = "ds4-prefix-cache-status-v1"
SESSION_APPEND_STATUS_FORMAT = "ds4-session-append-status-v1"

PREFIX_OPS = {"prefix_prepare", "prefix_pin", "prefix_fork", "prefix_release"}
SESSION_OPS = {"session_append", "session_decode", "session_release"}
STATUS_VALUES = {"prepared", "pinned", "forked", "released", "appended", "decoded", "blocked", "rejected", "miss"}
MISS_POLICIES = {"none", "defer", "reject"}
RUNTIME_HOOKS = {
	"prefix_prepare": "ds4_runtime_prefix_prepare",
	"prefix_pin": "ds4_runtime_prefix_pin",
	"prefix_fork": "ds4_runtime_prefix_fork",
	"prefix_release": "ds4_runtime_prefix_release",
	"session_append": "ds4_runtime_session_append",
	"session_decode": "ds4_runtime_session_decode",
	"session_release": "ds4_runtime_session_release",
}

IDENTITY_FIELDS = (
	"model_id",
	"runtime_id",
	"quantization_id",
	"tokenizer_sha256",
	"rope_config_sha256",
	"kv_format_id",
)


def load_json(path: Path) -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root must be an object")
	return obj


def _expect_string(errors: list[str], obj: dict[str, Any], key: str) -> None:
	if not isinstance(obj.get(key), str) or str(obj.get(key)).strip() == "":
		errors.append(f"{key} must be a non-empty string")


def _expect_bool(errors: list[str], obj: dict[str, Any], key: str) -> None:
	if not isinstance(obj.get(key), bool):
		errors.append(f"{key} must be boolean")


def _expect_int_list(errors: list[str], obj: dict[str, Any], key: str) -> None:
	value = obj.get(key)
	if not isinstance(value, list) or not all(isinstance(v, int) and v >= 0 for v in value):
		errors.append(f"{key} must be a list of non-negative integers")


def _expect_identity(errors: list[str], obj: dict[str, Any]) -> None:
	for key in IDENTITY_FIELDS:
		_expect_string(errors, obj, key)


def _validate_identity_match(errors: list[str], obj: dict[str, Any]) -> None:
	for key in IDENTITY_FIELDS:
		expected = obj.get(f"expected_{key}")
		if expected is not None and obj.get(key) != expected:
			errors.append(f"cache identity mismatch: {key}")


def _validate_runtime_hook(errors: list[str], obj: dict[str, Any]) -> None:
	operation = obj.get("operation")
	if obj.get("blocker_kind") != "missing_prefix_kv_runtime_hook":
		return
	_expect_string(errors, obj, "runtime_hook")
	expected = RUNTIME_HOOKS.get(str(operation))
	if expected is not None and obj.get("runtime_hook") != expected:
		errors.append(f"runtime_hook must be {expected} for {operation}")


def validate_prefix_manifest(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != PREFIX_MANIFEST_FORMAT:
		errors.append(f"format must be {PREFIX_MANIFEST_FORMAT}")
	for key in ("prefix_id", "provider_id", "prefix_handle", "token_ids_sha256"):
		_expect_string(errors, obj, key)
	_expect_identity(errors, obj)
	if not isinstance(obj.get("token_count"), int) or int(obj.get("token_count", 0)) <= 0:
		errors.append("token_count must be a positive integer")
	if "prefix_required" in obj:
		_expect_bool(errors, obj, "prefix_required")
	return errors


def validate_prefix_cache_status(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != PREFIX_CACHE_STATUS_FORMAT:
		errors.append(f"format must be {PREFIX_CACHE_STATUS_FORMAT}")
	for key in ("operation", "status", "prefix_id", "prefix_handle", "token_ids_sha256", "expected_token_ids_sha256", "blocker_kind", "blocker_detail"):
		_expect_string(errors, obj, key)
	_expect_identity(errors, obj)
	_validate_identity_match(errors, obj)
	if obj.get("operation") not in PREFIX_OPS:
		errors.append(f"operation must be one of {sorted(PREFIX_OPS)}")
	if obj.get("status") not in STATUS_VALUES:
		errors.append(f"status must be one of {sorted(STATUS_VALUES)}")
	_expect_bool(errors, obj, "cache_hit")
	_expect_bool(errors, obj, "prefix_required")
	if obj.get("miss_policy") not in MISS_POLICIES:
		errors.append(f"miss_policy must be one of {sorted(MISS_POLICIES)}")
	if obj.get("cache_hit") is True:
		if obj.get("token_ids_sha256") != obj.get("expected_token_ids_sha256"):
			errors.append("cache hit token SHA mismatch")
		if obj.get("status") in {"miss", "blocked", "rejected"}:
			errors.append("cache_hit=true cannot use miss/blocked/rejected status")
	if obj.get("cache_hit") is False and obj.get("prefix_required") is True:
		if obj.get("status") not in {"blocked", "rejected"} or obj.get("miss_policy") not in {"defer", "reject"}:
			errors.append("prefix_required=true with cache miss must explicitly defer or reject")
	if obj.get("status") in {"blocked", "rejected"} and str(obj.get("blocker_detail", "")).strip() == "":
		errors.append("blocked/rejected prefix cache status requires blocker_detail")
	_validate_runtime_hook(errors, obj)
	return errors


def validate_session_append_status(obj: dict[str, Any]) -> list[str]:
	errors: list[str] = []
	if obj.get("format") != SESSION_APPEND_STATUS_FORMAT:
		errors.append(f"format must be {SESSION_APPEND_STATUS_FORMAT}")
	for key in ("operation", "status", "session_id", "prefix_id", "prefix_handle", "suffix_token_ids_sha256", "kv_concat_mode", "blocker_kind", "blocker_detail"):
		_expect_string(errors, obj, key)
	_expect_identity(errors, obj)
	_validate_identity_match(errors, obj)
	if obj.get("operation") not in SESSION_OPS:
		errors.append(f"operation must be one of {sorted(SESSION_OPS)}")
	if obj.get("status") not in STATUS_VALUES:
		errors.append(f"status must be one of {sorted(STATUS_VALUES)}")
	if "suffix_token_ids" in obj:
		_expect_int_list(errors, obj, "suffix_token_ids")
	_expect_bool(errors, obj, "continuation_valid")
	if obj.get("kv_concat_mode") == "fragment_concat":
		errors.append("fragment KV concatenation is forbidden")
	if obj.get("continuation_valid") is False and obj.get("status") not in {"blocked", "rejected"}:
		errors.append("suffix append to invalid continuation must be blocked or rejected")
	if obj.get("operation") == "session_decode" and obj.get("status") == "decoded":
		if not isinstance(obj.get("committed_token_ids"), list) or len(obj.get("committed_token_ids", [])) == 0:
			errors.append("decoded session requires committed_token_ids")
		if not isinstance(obj.get("token_hash"), str) or not obj.get("token_hash", "").startswith("sha256:"):
			errors.append("decoded session requires sha256 token_hash")
	if obj.get("status") in {"blocked", "rejected"} and str(obj.get("blocker_detail", "")).strip() == "":
		errors.append("blocked/rejected session status requires blocker_detail")
	_validate_runtime_hook(errors, obj)
	return errors


def validate_artifact(obj: dict[str, Any]) -> list[str]:
	fmt = obj.get("format")
	if fmt == PREFIX_MANIFEST_FORMAT:
		return validate_prefix_manifest(obj)
	if fmt == PREFIX_CACHE_STATUS_FORMAT:
		return validate_prefix_cache_status(obj)
	if fmt == SESSION_APPEND_STATUS_FORMAT:
		return validate_session_append_status(obj)
	return [f"format must be {PREFIX_MANIFEST_FORMAT}, {PREFIX_CACHE_STATUS_FORMAT}, or {SESSION_APPEND_STATUS_FORMAT}"]


def main() -> int:
	ap = ArgumentParser()
	ap.add_argument("paths", nargs="+")
	args = ap.parse_args()
	failed = False
	for raw in args.paths:
		path = Path(raw)
		try:
			errors = validate_artifact(load_json(path))
		except (OSError, ValueError, json.JSONDecodeError) as exc:
			errors = [str(exc)]
		if errors:
			failed = True
			for error in errors:
				print(f"error: {path}: {error}", file=sys.stderr)
		else:
			print(f"ok: {path}")
	return 2 if failed else 0


if __name__ == "__main__":
	raise SystemExit(main())
