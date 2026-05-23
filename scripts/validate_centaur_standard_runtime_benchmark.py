#!/usr/bin/env python3
"""Validate Centaur standard-runtime model benchmark artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts._lib.json_utils import check_bool_field as check_bool
    from scripts._lib.json_utils import load_json as _load_json
except ImportError:
    from _lib.json_utils import check_bool_field as check_bool
    from _lib.json_utils import load_json as _load_json


FORMAT = "centaur-standard-runtime-model-benchmark-v1"
RUNTIMES = {"llama_cpp", "sglang", "vllm", "local_openai_compatible"}
MODEL_FORMATS = {"gguf", "hf", "safetensors", "other"}
OUTPUT_MODES = {"full_vocab", "constrained_candidate", "grammar_masked"}
MTP_UNVERIFIED_STATUS = "unverified - needs same-stack no-MTP baseline"
BLOCKER_KINDS = {
    "none",
    "runtime_install_blocked",
    "model_unavailable",
    "mtp_heads_unavailable",
    "benchmark_not_run",
    "endpoint_unavailable",
    "structured_output_not_candidate_only",
    "unsupported_runtime",
    "unknown",
}
FIXED_SPARK_COUNT_FIELDS = {"spark_count", "num_sparks", "world_size"}
SECRET_KEY_RE = re.compile(r"(^|[_\-.])(api[_\-.]?key|apikey|password|secret|access[_\-.]?token|auth[_\-.]?token|bearer)($|[_\-.])")
HASH_FIELDS = {"artifact_sha256"}
REQUIRED_FIELDS = (
    "format",
    "artifact_sha256",
    "benchmark_id",
    "provider_id",
    "model_id",
    "model_family",
    "runtime",
    "runtime_version",
    "model_format",
    "quantization",
    "hardware",
    "launch_command",
    "api_endpoint",
    "context_length",
    "mtp_supported",
    "mtp_enabled",
    "speculative_config",
    "ngram_spec_enabled",
    "batch_size",
    "prompt_shape",
    "output_mode",
    "tokens_per_second",
    "time_to_first_token_ms",
    "prompt_processing_tokens_per_second",
    "memory_used_gib",
    "parse_valid",
    "task_quality_score",
    "blocker_kind",
    "blocker_detail",
)


def default_benchmark_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted((root / "fixtures" / "standard_runtime_benchmarks").glob("*.json"))


def err(path: Path, msg: str) -> str:
    return f"{path}: {msg}"


def canonical_hash(obj: dict[str, Any]) -> str:
    payload = copy.deepcopy(obj)
    for field in HASH_FIELDS:
        payload.pop(field, None)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def as_str(obj: dict[str, Any], field: str, path: Path, errors: list[str], allow_empty: bool = False) -> str:
    value = obj.get(field)
    if not isinstance(value, str):
        errors.append(err(path, f"{field} must be a string"))
        return ""
    if value.strip() == "" and not allow_empty:
        errors.append(err(path, f"{field} must be a non-empty string"))
    return value.strip()


def check_int(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> int:
    value = obj.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append(err(path, f"{field} must be an integer"))
        return 0
    if value < 0:
        errors.append(err(path, f"{field} must be >= 0"))
    return int(value)


def check_number_or_null(obj: dict[str, Any], field: str, path: Path, errors: list[str]) -> float | None:
    value = obj.get(field)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(err(path, f"{field} must be a number or null"))
        return None
    if float(value) < 0.0:
        errors.append(err(path, f"{field} must be >= 0"))
    return float(value)


def check_optional_mtp_same_stack_baseline(obj: dict[str, Any], path: Path, errors: list[str]) -> None:
    mtp_enabled = obj.get("mtp_enabled")
    blocker = obj.get("blocker_kind")
    if mtp_enabled is not True or blocker != "none":
        return
    baseline = check_number_or_null(obj, "same_stack_no_mtp_baseline_tokens_per_second", path, errors) if "same_stack_no_mtp_baseline_tokens_per_second" in obj else None
    speedup = check_number_or_null(obj, "same_stack_speedup_vs_no_mtp", path, errors) if "same_stack_speedup_vs_no_mtp" in obj else None
    status = obj.get("same_stack_mtp_speedup_status")
    if baseline is None:
        if status != MTP_UNVERIFIED_STATUS:
            errors.append(err(path, f"MTP benchmark without same-stack no-MTP baseline must set same_stack_mtp_speedup_status={MTP_UNVERIFIED_STATUS!r}"))
        if speedup is not None:
            errors.append(err(path, "MTP speedup claim requires same-stack no-MTP baseline"))
        return
    if baseline <= 0.0:
        errors.append(err(path, "same_stack_no_mtp_baseline_tokens_per_second must be > 0 for MTP benchmark"))
        return
    if speedup is None:
        errors.append(err(path, "MTP benchmark with same-stack no-MTP baseline requires same_stack_speedup_vs_no_mtp"))
        return
    tps = obj.get("tokens_per_second")
    if isinstance(tps, (int, float)) and not isinstance(tps, bool):
        expected = float(tps) / baseline
        if abs(float(speedup) - expected) > 1e-6:
            errors.append(err(path, "same_stack_speedup_vs_no_mtp must equal tokens_per_second / same_stack_no_mtp_baseline_tokens_per_second"))


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


def validate_benchmark(obj: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in obj:
            errors.append(err(path, f"missing required field: {field}"))
    for field in FIXED_SPARK_COUNT_FIELDS:
        if field in obj:
            errors.append(err(path, f"fixed Spark count field is not allowed: {field}"))
    if obj.get("format") != FORMAT:
        errors.append(err(path, f"format must be {FORMAT}"))
    actual_hash = obj.get("artifact_sha256")
    if not isinstance(actual_hash, str) or len(actual_hash) != 64:
        errors.append(err(path, "artifact_sha256 must be a 64-character sha256 hex string"))
    elif actual_hash != canonical_hash(obj):
        errors.append(err(path, "artifact_sha256 does not match canonical artifact hash"))
    runtime = as_str(obj, "runtime", path, errors)
    model_format = as_str(obj, "model_format", path, errors)
    output_mode = as_str(obj, "output_mode", path, errors)
    blocker = as_str(obj, "blocker_kind", path, errors)
    as_str(obj, "benchmark_id", path, errors)
    as_str(obj, "provider_id", path, errors)
    as_str(obj, "model_id", path, errors)
    as_str(obj, "model_family", path, errors)
    as_str(obj, "runtime_version", path, errors, allow_empty=True)
    as_str(obj, "quantization", path, errors)
    as_str(obj, "launch_command", path, errors, allow_empty=True)
    as_str(obj, "api_endpoint", path, errors, allow_empty=True)
    as_str(obj, "prompt_shape", path, errors)
    as_str(obj, "blocker_detail", path, errors, allow_empty=(blocker == "none"))
    if runtime and runtime not in RUNTIMES:
        errors.append(err(path, f"unknown runtime: {runtime}"))
    if model_format and model_format not in MODEL_FORMATS:
        errors.append(err(path, f"unknown model_format: {model_format}"))
    if output_mode and output_mode not in OUTPUT_MODES:
        errors.append(err(path, f"unknown output_mode: {output_mode}"))
    if blocker and blocker not in BLOCKER_KINDS:
        errors.append(err(path, f"unknown blocker_kind: {blocker}"))
    if not isinstance(obj.get("hardware"), dict):
        errors.append(err(path, "hardware must be an object"))
    if not isinstance(obj.get("speculative_config"), dict):
        errors.append(err(path, "speculative_config must be an object"))
    check_int(obj, "context_length", path, errors)
    check_int(obj, "batch_size", path, errors)
    mtp_supported = check_bool(obj, "mtp_supported", path, errors)
    mtp_enabled = check_bool(obj, "mtp_enabled", path, errors)
    check_bool(obj, "ngram_spec_enabled", path, errors)
    parse_valid = check_bool(obj, "parse_valid", path, errors)
    tps = check_number_or_null(obj, "tokens_per_second", path, errors)
    ttft = check_number_or_null(obj, "time_to_first_token_ms", path, errors)
    prompt_tps = check_number_or_null(obj, "prompt_processing_tokens_per_second", path, errors)
    memory = check_number_or_null(obj, "memory_used_gib", path, errors)
    quality = check_number_or_null(obj, "task_quality_score", path, errors)
    if mtp_enabled and not mtp_supported:
        errors.append(err(path, "mtp_enabled requires mtp_supported=true"))
    if blocker == "none":
        if tps is None or tps <= 0.0:
            errors.append(err(path, "successful benchmark requires tokens_per_second > 0"))
        if ttft is None:
            errors.append(err(path, "successful benchmark requires time_to_first_token_ms"))
        if prompt_tps is None:
            errors.append(err(path, "successful benchmark requires prompt_processing_tokens_per_second"))
        if memory is None:
            errors.append(err(path, "successful benchmark requires memory_used_gib"))
        if not parse_valid:
            errors.append(err(path, "successful benchmark requires parse_valid=true"))
        if output_mode == "constrained_candidate" and obj.get("structured_output_semantics") != "candidate_only_scoring":
            errors.append(err(path, "constrained_candidate success requires candidate_only_scoring semantics"))
    else:
        if tps not in (None, 0.0):
            errors.append(err(path, "blocked benchmark must not claim tokens_per_second"))
        if parse_valid:
            errors.append(err(path, "blocked benchmark must not set parse_valid=true"))
    if quality is not None and quality > 100.0:
        errors.append(err(path, "task_quality_score must be <= 100"))
    check_optional_mtp_same_stack_baseline(obj, path, errors)
    scan_secret_keys(obj, path, errors)
    return errors


def load_benchmark(path: Path) -> dict[str, Any]:
    return _load_json(path, "root JSON")


def validate_paths(paths: list[Path]) -> dict[str, Any]:
    all_errors: list[str] = []
    for path in paths:
        try:
            obj = load_benchmark(path)
        except Exception as e:
            all_errors.append(f"{path}: {e}")
            continue
        all_errors.extend(validate_benchmark(obj, path))
    return {
        "ok": len(all_errors) == 0,
        "benchmark_count": len(paths),
        "errors": all_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Centaur standard-runtime model benchmark artifacts.")
    parser.add_argument("benchmarks", nargs="*", help="Benchmark JSON paths. Defaults to fixtures/standard_runtime_benchmarks/*.json.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()
    paths = [Path(item) for item in args.benchmarks] if args.benchmarks else default_benchmark_paths()
    result = validate_paths(paths)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if result["ok"]:
            print(f"ok: validated {result['benchmark_count']} standard-runtime benchmark artifact(s)")
        else:
            for item in result["errors"]:
                print(item)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
