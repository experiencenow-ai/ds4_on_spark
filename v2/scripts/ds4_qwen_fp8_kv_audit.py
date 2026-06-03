#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_CONTRACTS = ROOT / "profiles" / "runtime_contracts"
KV_DEPLOYMENTS = ROOT / "profiles" / "kv_cache"


class AuditError(RuntimeError):
    pass


def main() -> int:
    checks: list[str] = []
    errors: list[str] = []

    for path in sorted(RUNTIME_CONTRACTS.glob("*.json")):
        data = _load_json(path)
        if not _is_qwen_profile(path, data):
            continue
        args = _launch_args(data)
        _check_arg_value(path, args, "--kv-cache-dtype", "fp8", errors)
        _check_arg_value(path, args, "--attention-backend", "TRITON_ATTN", errors)
        _check_no_mnt_nvme(path, data, errors)
        checks.append(f"runtime contract {path.name} has explicit fp8 KV and TRITON_ATTN")

    for path in sorted(KV_DEPLOYMENTS.glob("*.json")):
        data = _load_json(path)
        if not _is_qwen_profile(path, data):
            continue
        args = _deployment_args(data)
        if args:
            _check_arg_value(path, args, "--kv-cache-dtype", "fp8", errors)
            _check_arg_value(path, args, "--attention-backend", "TRITON_ATTN", errors)
        elif data.get("runtime_contract_id"):
            checks.append(f"kv deployment {path.name} delegates launch args to {data['runtime_contract_id']}")
        else:
            errors.append(f"{path}: Qwen KV deployment has neither launch args nor runtime_contract_id")
        _check_qwen_cache_namespace(path, data, errors)
        _check_no_mnt_nvme(path, data, errors)
        checks.append(f"kv deployment {path.name} uses explicit fp8 KV namespace")

    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        raise AuditError(f"{len(errors)} Qwen FP8 KV profile checks failed")
    for check in checks:
        print(f"PASS: {check}")
    return 0


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise AuditError(f"{path}: expected JSON object")
    return data


def _is_qwen_profile(path: Path, data: dict[str, Any]) -> bool:
    needles = [
        path.name,
        str(data.get("contract_id", "")),
        str(data.get("deployment_id", "")),
        str(data.get("profile_id", "")),
        str(data.get("model_id", "")),
        str(data.get("served_model_name", "")),
        " ".join(str(item) for item in data.get("profile_ids", [])),
    ]
    return any("qwen" in item.lower() for item in needles)


def _launch_args(data: dict[str, Any]) -> list[str]:
    launch = data.get("launch", {})
    if not isinstance(launch, dict):
        return []
    return _string_list(launch.get("args", []))


def _deployment_args(data: dict[str, Any]) -> list[str]:
    if "extra_args" in data:
        return _string_list(data.get("extra_args", []))
    if "launch_args" in data:
        return _string_list(data.get("launch_args", []))
    launch = data.get("launch", {})
    if isinstance(launch, dict):
        return _string_list(launch.get("args", []))
    return []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _arg_value(args: list[str], flag: str) -> str | None:
    try:
        index = args.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    return args[index + 1]


def _check_arg_value(path: Path, args: list[str], flag: str, expected: str, errors: list[str]) -> None:
    value = _arg_value(args, flag)
    if value != expected:
        errors.append(f"{path}: expected {flag} {expected}, found {value!r}")


def _check_qwen_cache_namespace(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    for label, value in _walk_strings(data):
        if "ds4_lmcache" not in value:
            continue
        if "qwen" not in value.lower():
            continue
        if "fp8kv" not in value.lower():
            errors.append(f"{path}: Qwen cache path {label} is not fp8kv-namespaced: {value}")


def _check_no_mnt_nvme(path: Path, data: dict[str, Any], errors: list[str]) -> None:
    for label, value in _walk_strings(data):
        if "/mnt/nvme" in value:
            errors.append(f"{path}: Qwen profile still references /mnt/nvme at {label}: {value}")


def _walk_strings(value: Any, prefix: str = "$") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(prefix, value)]
    if isinstance(value, list):
        rows: list[tuple[str, str]] = []
        for index, item in enumerate(value):
            rows.extend(_walk_strings(item, f"{prefix}[{index}]"))
        return rows
    if isinstance(value, dict):
        rows = []
        for key, item in value.items():
            rows.extend(_walk_strings(item, f"{prefix}.{key}"))
        return rows
    return []


if __name__ == "__main__":
    raise SystemExit(main())
