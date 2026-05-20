#!/usr/bin/env python3
"""Validate ds4-vllm-pp-runtime-probe-v1 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-pp-runtime-probe-v1"
WARM_FORMAT = "ds4-vllm-pp-warm-runtime-probe-v1"
REQUIRED_FIELDS = (
    "format",
    "status",
    "model",
    "pipeline_parallel_size",
    "tensor_parallel_size",
    "max_tokens",
    "max_model_len",
    "max_num_seqs",
    "max_num_batched_tokens",
    "gpu_memory_utilization",
    "kv_cache_dtype",
    "prompt_sha256",
    "vllm_host_ip",
    "ray_address",
    "vllm_pp_layer_partition",
)
PASSED_FIELDS = (
    "load_s",
    "generate_s",
    "total_s",
    "generated_tokens",
    "generation_tps",
    "token_ids",
    "token_hash",
)
WARM_REQUIRED_FIELDS = (
    "format",
    "status",
    "model",
    "pipeline_parallel_size",
    "tensor_parallel_size",
    "warm_tokens",
    "measure_tokens",
    "max_model_len",
    "max_num_seqs",
    "max_num_batched_tokens",
    "gpu_memory_utilization",
    "kv_cache_dtype",
    "prompt_sha256",
    "vllm_host_ip",
    "ray_address",
    "vllm_pp_layer_partition",
    "enforce_eager",
)
WARM_PASSED_FIELDS = (
    "load_s",
    "warm_s",
    "measure_s",
    "total_s",
    "warm_generated_tokens",
    "measured_generated_tokens",
    "warm_tps",
    "measured_tps",
    "warm_token_ids",
    "measured_token_ids",
    "measured_token_hash",
)


def default_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted((root / "fixtures" / "vllm_pp_runtime_probe").glob("*.json"))


def err(path: Path, msg: str) -> str:
    return f"{path}: {msg}"


def _num(obj: dict[str, Any], key: str, path: Path, errors: list[str], *, positive: bool = False) -> float:
    value = obj.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(err(path, f"{key} must be a number"))
        return 0.0
    number = float(value)
    if positive and number <= 0.0:
        errors.append(err(path, f"{key} must be > 0"))
    elif not positive and number < 0.0:
        errors.append(err(path, f"{key} must be >= 0"))
    return number


def _str(obj: dict[str, Any], key: str, path: Path, errors: list[str]) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        errors.append(err(path, f"{key} must be a string"))
        return ""
    if value.strip() == "":
        errors.append(err(path, f"{key} must be non-empty"))
    return value


def _validate_common(
    obj: dict[str, Any],
    path: Path,
    errors: list[str],
    required_fields: tuple[str, ...],
) -> str:
    for field in required_fields:
        if field not in obj:
            errors.append(err(path, f"missing required field: {field}"))
    status = obj.get("status")
    if status not in {"started", "passed", "failed"}:
        errors.append(err(path, "status must be started, passed, or failed"))
    _str(obj, "model", path, errors)
    _str(obj, "prompt_sha256", path, errors)
    _str(obj, "vllm_host_ip", path, errors)
    _str(obj, "ray_address", path, errors)
    _str(obj, "vllm_pp_layer_partition", path, errors)
    _num(obj, "pipeline_parallel_size", path, errors, positive=True)
    _num(obj, "tensor_parallel_size", path, errors, positive=True)
    _num(obj, "max_model_len", path, errors, positive=True)
    _num(obj, "max_num_seqs", path, errors, positive=True)
    _num(obj, "max_num_batched_tokens", path, errors, positive=True)
    _num(obj, "gpu_memory_utilization", path, errors, positive=True)
    if status == "failed":
        _str(obj, "error_type", path, errors)
        _str(obj, "error", path, errors)
    return str(status)


def _validate_token_ids(
    obj: dict[str, Any],
    path: Path,
    errors: list[str],
    *,
    count_key: str,
    ids_key: str,
) -> int:
    generated = int(_num(obj, count_key, path, errors, positive=True))
    token_ids = obj.get(ids_key)
    if not isinstance(token_ids, list) or not all(isinstance(item, int) for item in token_ids):
        errors.append(err(path, f"{ids_key} must be a list of integers"))
    elif len(token_ids) != generated:
        errors.append(err(path, f"{ids_key} length must equal {count_key}"))
    return generated


def _validate_runtime_artifact(obj: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    status = _validate_common(obj, path, errors, REQUIRED_FIELDS)
    _num(obj, "max_tokens", path, errors, positive=True)
    if status == "passed":
        for field in PASSED_FIELDS:
            if field not in obj:
                errors.append(err(path, f"missing passed field: {field}"))
        _validate_token_ids(obj, path, errors, count_key="generated_tokens", ids_key="token_ids")
        _num(obj, "generation_tps", path, errors, positive=True)
        _num(obj, "load_s", path, errors, positive=True)
        _num(obj, "generate_s", path, errors, positive=True)
        _str(obj, "token_hash", path, errors)
    return errors


def _validate_warm_artifact(obj: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    status = _validate_common(obj, path, errors, WARM_REQUIRED_FIELDS)
    _num(obj, "warm_tokens", path, errors, positive=True)
    _num(obj, "measure_tokens", path, errors, positive=True)
    if not isinstance(obj.get("enforce_eager"), bool):
        errors.append(err(path, "enforce_eager must be a boolean"))
    if status == "passed":
        for field in WARM_PASSED_FIELDS:
            if field not in obj:
                errors.append(err(path, f"missing passed field: {field}"))
        _validate_token_ids(
            obj,
            path,
            errors,
            count_key="warm_generated_tokens",
            ids_key="warm_token_ids",
        )
        _validate_token_ids(
            obj,
            path,
            errors,
            count_key="measured_generated_tokens",
            ids_key="measured_token_ids",
        )
        _num(obj, "load_s", path, errors, positive=True)
        _num(obj, "warm_s", path, errors, positive=True)
        _num(obj, "measure_s", path, errors, positive=True)
        _num(obj, "warm_tps", path, errors, positive=True)
        _num(obj, "measured_tps", path, errors, positive=True)
        _str(obj, "measured_token_hash", path, errors)
    return errors


def validate_artifact(obj: dict[str, Any], path: Path) -> list[str]:
    fmt = obj.get("format")
    if fmt == FORMAT:
        return _validate_runtime_artifact(obj, path)
    if fmt == WARM_FORMAT:
        return _validate_warm_artifact(obj, path)
    return [err(path, f"format must be {FORMAT} or {WARM_FORMAT}")]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("root JSON must be an object")
    return obj


def validate_paths(paths: list[Path]) -> dict[str, Any]:
    errors: list[str] = []
    for path in paths:
        try:
            obj = load_json(path)
        except Exception as e:
            errors.append(err(path, str(e)))
            continue
        errors.extend(validate_artifact(obj, path))
    return {"ok": len(errors) == 0, "artifact_count": len(paths), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="*", help="Artifact paths. Defaults to fixtures/vllm_pp_runtime_probe/*.json.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = [Path(item) for item in args.artifacts] if args.artifacts else default_paths()
    result = validate_paths(paths)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"ok: validated {result['artifact_count']} vLLM PP runtime probe artifact(s)")
    else:
        for item in result["errors"]:
            print(item)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
