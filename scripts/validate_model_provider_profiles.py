#!/usr/bin/env python3
"""Validate DS4 model provider profile fixtures."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FORMATS = {"ds4-model-provider-profile-v1", "centaur-model-provider-profile-v1"}
TIERS = {"deterministic", "local_small", "local_coder", "near_frontier_local", "frontier_api"}
RUNTIMES = {"deterministic", "vllm", "sglang", "llama_cpp", "local_openai_compatible", "ds4_custom_runtime", "ds4_layer_pipeline", "simulator", "frontier_api"}
PROVIDER_KINDS = {"deterministic_tool", "independent_lane", "layer_pipeline", "openai_compatible_endpoint", "simulator", "external_placeholder"}
SECRET_KEY_RE = re.compile(r"(^|[_\-.])(api[_\-.]?key|apikey|password|secret|access[_\-.]?token|auth[_\-.]?token|bearer)($|[_\-.])")
FIXED_SPARK_COUNT_FIELDS = {"spark_count", "num_sparks", "world_size"}
REQUIRED_FIELDS = (
    "format",
    "provider_id",
    "tier",
    "model_id",
    "runtime",
    "endpoint",
    "node_ids",
    "provider_kind",
    "supported_lanes",
    "preferred_batch_tokens",
    "minimum_batch_tokens",
    "maximum_wait_ms",
    "measured_input_tps",
    "measured_output_tps",
    "quality_scores",
    "last_probe_artifact",
)


def repo_root() -> Path:
	return Path(__file__).resolve().parents[1]


def default_profile_paths() -> list[Path]:
	return sorted((repo_root() / "fixtures" / "model_providers").glob("*.json"))


def err(path: Path, msg: str) -> str:
	return f"{path}: {msg}"


def as_str(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> str:
	value = obj.get(field)
	if not isinstance(value, str) or value.strip() == "":
		errors.append(err(path, f"{field} must be a non-empty string"))
		return ""
	return value.strip()


def check_number_or_null(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> float | None:
	value = obj.get(field)
	if value is None:
		return None
	if not isinstance(value, (int, float)) or isinstance(value, bool):
		errors.append(err(path, f"{field} must be a number or null"))
		return None
	if float(value) < 0.0:
		errors.append(err(path, f"{field} must be >= 0"))
		return None
	return float(value)


def check_int_field(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> int:
	value = obj.get(field)
	if not isinstance(value, int) or isinstance(value, bool):
		errors.append(err(path, f"{field} must be an integer"))
		return 0
	if value < 0:
		errors.append(err(path, f"{field} must be >= 0"))
		return 0
	return int(value)


def check_string_list(obj: dict[str, Any], field: str, path: Path, errors: list[str], allow_empty: bool) -> None:
	value = obj.get(field)
	if not isinstance(value, list):
		errors.append(err(path, f"{field} must be a list"))
		return
	if len(value) == 0 and not allow_empty:
		errors.append(err(path, f"{field} must not be empty"))
	for item in value:
		if not isinstance(item, str) or item.strip() == "":
			errors.append(err(path, f"{field} entries must be non-empty strings"))
			return


def is_external_ref(value: str) -> bool:
	return value.startswith(("http://", "https://"))


def check_repo_ref(value: str, field: str, path: Path, errors: list[str], root: Path) -> None:
	ref = value.strip()
	if ref == "" or is_external_ref(ref):
		return
	ref_path = Path(ref)
	if ref_path.is_absolute() or ".." in ref_path.parts:
		errors.append(err(path, f"{field} must be a repo-relative path or URL"))
		return
	if not (root / ref_path).is_file():
		errors.append(err(path, f"{field} references missing repo file: {ref}"))


def check_repo_ref_list(obj: dict[str, Any], field: str, path: Path, errors: list[str], root: Path) -> None:
	value = obj.get(field)
	if value is None:
		return
	if not isinstance(value, list):
		errors.append(err(path, f"{field} must be a list when present"))
		return
	for item in value:
		if not isinstance(item, str) or item.strip() == "":
			errors.append(err(path, f"{field} entries must be non-empty strings"))
			return
		check_repo_ref(item, field, path, errors, root)


def scan_secret_keys(value: Any, path: Path, errors: list[str], key_path: str = "") -> None:
	if isinstance(value, dict):
		for key, child in value.items():
			lower = str(key).lower()
			if SECRET_KEY_RE.search(lower) is not None:
				errors.append(err(path, f"secret-looking key is not allowed: {key_path + str(key)}"))
			scan_secret_keys(child, path, errors, key_path + str(key) + ".")
	elif isinstance(value, list):
		for i, child in enumerate(value):
			scan_secret_keys(child, path, errors, key_path + f"{i}.")
	elif isinstance(value, str):
		lower = value.lower()
		if lower.startswith(("sk-", "ghp_", "gho_", "bearer ")):
			errors.append(err(path, "secret-looking value is not allowed"))


def validate_profile(obj: dict[str, Any], path: Path, root: Path | None = None) -> list[str]:
	errors: list[str] = []
	root = repo_root() if root is None else root
	for field in REQUIRED_FIELDS:
		if field not in obj:
			errors.append(err(path, f"missing required field: {field}"))
	for field in FIXED_SPARK_COUNT_FIELDS:
		if field in obj:
			errors.append(err(path, f"fixed Spark count field is not allowed: {field}"))
	if obj.get("format") not in FORMATS:
		errors.append(err(path, f"format must be one of {sorted(FORMATS)}"))
	tier = as_str(obj, "tier", path, errors)
	runtime = as_str(obj, "runtime", path, errors)
	provider_kind = as_str(obj, "provider_kind", path, errors)
	as_str(obj, "provider_id", path, errors)
	as_str(obj, "model_id", path, errors)
	if tier and tier not in TIERS:
		errors.append(err(path, f"unknown tier: {tier}"))
	if runtime and runtime not in RUNTIMES:
		errors.append(err(path, f"unknown runtime: {runtime}"))
	if provider_kind and provider_kind not in PROVIDER_KINDS:
		errors.append(err(path, f"unknown provider_kind: {provider_kind}"))
	endpoint = obj.get("endpoint")
	if endpoint is not None and not isinstance(endpoint, dict):
		errors.append(err(path, "endpoint must be an object or null"))
	check_string_list(obj, "node_ids", path, errors, allow_empty=True)
	check_string_list(obj, "supported_lanes", path, errors, allow_empty=False)
	preferred = check_int_field(obj, "preferred_batch_tokens", path, errors)
	minimum = check_int_field(obj, "minimum_batch_tokens", path, errors)
	check_int_field(obj, "maximum_wait_ms", path, errors)
	if preferred < minimum:
		errors.append(err(path, "preferred_batch_tokens must be >= minimum_batch_tokens"))
	measured_input = check_number_or_null(obj, "measured_input_tps", path, errors)
	measured_output = check_number_or_null(obj, "measured_output_tps", path, errors)
	last_probe = obj.get("last_probe_artifact")
	if not isinstance(last_probe, str):
		errors.append(err(path, "last_probe_artifact must be a string"))
	elif ((measured_input is not None and measured_input > 0.0) or (measured_output is not None and measured_output > 0.0)) and last_probe.strip() == "":
		errors.append(err(path, "measured throughput requires last_probe_artifact"))
	elif isinstance(last_probe, str):
		check_repo_ref(last_probe, "last_probe_artifact", path, errors, root)
	check_repo_ref_list(obj, "benchmark_refs", path, errors, root)
	check_repo_ref_list(obj, "source_refs", path, errors, root)
	production_eligible = obj.get("production_eligible")
	if production_eligible is not None and not isinstance(production_eligible, bool):
		errors.append(err(path, "production_eligible must be a boolean when present"))
	if production_eligible is True:
		if measured_output is None or measured_output <= 0.0:
			errors.append(err(path, "production_eligible requires measured_output_tps > 0"))
		if not isinstance(last_probe, str) or last_probe.strip() == "":
			errors.append(err(path, "production_eligible requires last_probe_artifact"))
		if "blocked_reason" in obj:
			errors.append(err(path, "production_eligible cannot include blocked_reason"))
		if isinstance(endpoint, dict) and str(endpoint.get("status", "")).lower() == "blocked":
			errors.append(err(path, "production_eligible endpoint status cannot be blocked"))
	quality = obj.get("quality_scores")
	if not isinstance(quality, dict):
		errors.append(err(path, "quality_scores must be an object"))
	else:
		for key, value in quality.items():
			if value is None:
				continue
			if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < 0.0 or float(value) > 100.0:
				errors.append(err(path, f"quality_scores.{key} must be in [0,100] or null"))
	scan_secret_keys(obj, path, errors)
	return errors


def load_profile(path: Path) -> dict[str, Any]:
	with path.open("r", encoding="utf-8") as f:
		obj = json.load(f)
	if not isinstance(obj, dict):
		raise ValueError(f"{path}: root JSON must be an object")
	return obj


def validate_paths(paths: list[Path]) -> dict[str, Any]:
	all_errors: list[str] = []
	root = repo_root()
	for path in paths:
		try:
			obj = load_profile(path)
		except Exception as e:
			all_errors.append(f"{path}: {e}")
			continue
		all_errors.extend(validate_profile(obj, path, root))
	return {
		"ok": len(all_errors) == 0,
		"profile_count": len(paths),
		"errors": all_errors,
	}


def main() -> int:
	parser = argparse.ArgumentParser(description="Validate DS4 model provider profile fixtures.")
	parser.add_argument("profiles", nargs="*", help="Profile JSON paths. Defaults to fixtures/model_providers/*.json.")
	parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
	args = parser.parse_args()
	paths = [Path(item) for item in args.profiles] if args.profiles else default_profile_paths()
	result = validate_paths(paths)
	if args.json:
		print(json.dumps(result, indent=2, sort_keys=True))
	else:
		if result["ok"]:
			print(f"ok: validated {result['profile_count']} provider profile(s)")
		else:
			for item in result["errors"]:
				print(item)
	return 0 if result["ok"] else 1


if __name__ == "__main__":
	raise SystemExit(main())
