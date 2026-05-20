#!/usr/bin/env python3
"""Validate ds4-vllm-pp-runtime-probe-v1 artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-pp-runtime-probe-v1"
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


def validate_artifact(obj: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in obj:
            errors.append(err(path, f"missing required field: {field}"))
    if obj.get("format") != FORMAT:
        errors.append(err(path, f"format must be {FORMAT}"))
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
    _num(obj, "max_tokens", path, errors, positive=True)
    _num(obj, "max_model_len", path, errors, positive=True)
    _num(obj, "max_num_seqs", path, errors, positive=True)
    _num(obj, "max_num_batched_tokens", path, errors, positive=True)
    _num(obj, "gpu_memory_utilization", path, errors, positive=True)
    if status == "passed":
        for field in PASSED_FIELDS:
            if field not in obj:
                errors.append(err(path, f"missing passed field: {field}"))
        generated = int(_num(obj, "generated_tokens", path, errors, positive=True))
        _num(obj, "generation_tps", path, errors, positive=True)
        _num(obj, "load_s", path, errors, positive=True)
        _num(obj, "generate_s", path, errors, positive=True)
        token_ids = obj.get("token_ids")
        if not isinstance(token_ids, list) or not all(isinstance(item, int) for item in token_ids):
            errors.append(err(path, "token_ids must be a list of integers"))
        elif len(token_ids) != generated:
            errors.append(err(path, "token_ids length must equal generated_tokens"))
        _str(obj, "token_hash", path, errors)
    if status == "failed":
        _str(obj, "error_type", path, errors)
        _str(obj, "error", path, errors)
    return errors


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
