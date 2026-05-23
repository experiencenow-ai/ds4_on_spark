#!/usr/bin/env python3
"""Shared strict JSON helpers for DS4 scripts."""

from __future__ import annotations

import json
import copy
import hashlib
from pathlib import Path
from typing import Any, Callable


def canonical_bytes(obj: Any) -> bytes:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
	return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any], drop: tuple[str, ...] = ("artifact_sha256", "artifact_hash")) -> str:
	tmp = copy.deepcopy(obj)
	for key in drop:
		tmp.pop(key, None)
	return sha256_obj(tmp)


def is_sha256_text(value: Any, allow_empty: bool = False) -> bool:
	if allow_empty and value == "":
		return True
	if not isinstance(value, str):
		return False
	return value.startswith("sha256:") and len(value) == 71


def canonical_hash(obj: dict[str, Any], drop: tuple[str, ...] = ("artifact_sha256",)) -> str:
	payload = copy.deepcopy(obj)
	for key in drop:
		payload.pop(key, None)
	data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
	return hashlib.sha256(data).hexdigest()


def load_json(path: Path, root_label: str = "root") -> dict[str, Any]:
	obj = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: {root_label} must be an object")
	return obj


def number_or_none(raw: Any) -> float | None:
	if raw is None:
		return None
	if isinstance(raw, (int, float)):
		return float(raw)
	try:
		return float(str(raw).strip())
	except (TypeError, ValueError):
		return None


def check_bool_field(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> bool:
	value = obj.get(field)
	if not isinstance(value, bool):
		errors.append(f"{path}: {field} must be a boolean")
		return False
	return bool(value)


def check_non_empty_string_field(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> str:
	value = obj.get(field)
	if not isinstance(value, str) or value.strip() == "":
		errors.append(f"{path}: {field} must be a non-empty string")
		return ""
	return value.strip()


def max_number(values: Any) -> float:
	if not isinstance(values, list):
		return 0.0
	nums = [float(v) for v in values if isinstance(v, (int, float))]
	return max(nums) if nums else 0.0


def validate_json_paths(paths: list[Path], validate_func: Callable[[dict[str, Any], Path], list[str]], load_func: Callable[[Path], dict[str, Any]] = load_json) -> dict[str, Any]:
	all_errors: list[str] = []
	for path in paths:
		try:
			all_errors.extend(validate_func(load_func(path), path))
		except Exception as e:
			all_errors.append(f"{path}: {e}")
	return {"ok": len(all_errors) == 0, "errors": all_errors}


def make_validate_paths(validate_func: Callable[[dict[str, Any], Path], list[str]], load_func: Callable[[Path], dict[str, Any]] = load_json) -> Callable[[list[Path]], dict[str, Any]]:
	def _validate_paths(paths: list[Path]) -> dict[str, Any]:
		return validate_json_paths(paths, validate_func, load_func)
	return _validate_paths
