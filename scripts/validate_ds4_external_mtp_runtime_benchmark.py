#!/usr/bin/env python3
"""Validate DS4 external MTP runtime benchmark artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-external-mtp-runtime-benchmark-v1"
RUNTIMES = {"llama_cpp", "sglang", "vllm"}
STATUSES = {"passed", "failed", "blocked", "not_run"}
BLOCKERS = {
    "none",
    "runtime_not_installed",
    "unsupported_model_architecture",
    "checkpoint_unavailable",
    "model_format_mismatch",
    "insufficient_gpu_count",
    "spark_host_unreachable",
    "docker_permission_denied",
    "benchmark_not_run",
    "unknown",
}
HASH_FIELDS = {"artifact_sha256", "artifact_hash"}
REQUIRED_FIELDS = (
    "format",
    "artifact_sha256",
    "artifact_hash",
    "run_id",
    "checked_at",
    "target_model_id",
    "model_artifact",
    "prompt_sha256",
    "spark_reachability",
    "runtime_attempts",
    "summary",
)
ATTEMPT_FIELDS = (
    "runtime",
    "benchmark_status",
    "mtp_supported",
    "ds4_model_supported",
    "baseline_generation_tps",
    "mtp_generation_tps",
    "speedup_vs_baseline",
    "blocker_kind",
    "blocker_detail",
)


def default_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted((root / "fixtures" / "external_mtp_runtime_bench").glob("*.json"))


def err(path: Path, msg: str) -> str:
    return f"{path}: {msg}"


def canonical_hash(obj: dict[str, Any]) -> str:
    payload = copy.deepcopy(obj)
    for field in HASH_FIELDS:
        payload.pop(field, None)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _str(obj: dict[str, Any], key: str, path: Path, errors: list[str], allow_empty: bool = False) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        errors.append(err(path, f"{key} must be a string"))
        return ""
    if value.strip() == "" and not allow_empty:
        errors.append(err(path, f"{key} must be non-empty"))
    return value.strip()


def _bool(obj: dict[str, Any], key: str, path: Path, errors: list[str]) -> bool:
    value = obj.get(key)
    if not isinstance(value, bool):
        errors.append(err(path, f"{key} must be a boolean"))
        return False
    return value


def _number_or_null(obj: dict[str, Any], key: str, path: Path, errors: list[str]) -> float | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(err(path, f"{key} must be a number or null"))
        return None
    if float(value) < 0.0:
        errors.append(err(path, f"{key} must be >= 0"))
    return float(value)


def validate_attempt(obj: dict[str, Any], path: Path, idx: int) -> list[str]:
    errors: list[str] = []
    label = Path(f"{path}#runtime_attempts[{idx}]")
    for field in ATTEMPT_FIELDS:
        if field not in obj:
            errors.append(err(label, f"missing required field: {field}"))
    runtime = _str(obj, "runtime", label, errors)
    status = _str(obj, "benchmark_status", label, errors)
    blocker = _str(obj, "blocker_kind", label, errors)
    mtp_supported = _bool(obj, "mtp_supported", label, errors)
    _bool(obj, "ds4_model_supported", label, errors)
    baseline = _number_or_null(obj, "baseline_generation_tps", label, errors)
    mtp = _number_or_null(obj, "mtp_generation_tps", label, errors)
    speedup = _number_or_null(obj, "speedup_vs_baseline", label, errors)
    if runtime and runtime not in RUNTIMES:
        errors.append(err(label, f"unknown runtime: {runtime}"))
    if status and status not in STATUSES:
        errors.append(err(label, f"unknown benchmark_status: {status}"))
    if blocker and blocker not in BLOCKERS:
        errors.append(err(label, f"unknown blocker_kind: {blocker}"))
    if status == "passed":
        if blocker != "none":
            errors.append(err(label, "passed attempt must use blocker_kind=none"))
        if baseline is None or baseline <= 0.0:
            errors.append(err(label, "passed attempt requires baseline_generation_tps > 0"))
        if mtp is None or mtp <= 0.0:
            errors.append(err(label, "passed attempt requires mtp_generation_tps > 0"))
        if speedup is None or speedup <= 0.0:
            errors.append(err(label, "passed attempt requires speedup_vs_baseline > 0"))
        if baseline is not None and mtp is not None and speedup is not None:
            expected = mtp / baseline
            if abs(expected - speedup) > 0.005:
                errors.append(err(label, "speedup_vs_baseline must match mtp/baseline"))
    else:
        if blocker == "none":
            errors.append(err(label, "blocked/failed attempt requires a precise blocker_kind"))
        _str(obj, "blocker_detail", label, errors)
        if baseline is not None or mtp is not None or speedup is not None:
            errors.append(err(label, "blocked/failed attempt must not claim speed metrics"))
    if obj.get("mtp_enabled") is True and not mtp_supported:
        errors.append(err(label, "mtp_enabled requires mtp_supported=true"))
    return errors


def validate_artifact(obj: dict[str, Any], path: Path) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in obj:
            errors.append(err(path, f"missing required field: {field}"))
    if obj.get("format") != FORMAT:
        errors.append(err(path, f"format must be {FORMAT}"))
    actual = obj.get("artifact_sha256")
    if not isinstance(actual, str) or len(actual) != 64:
        errors.append(err(path, "artifact_sha256 must be a 64-character sha256 hex string"))
    elif actual != canonical_hash(obj):
        errors.append(err(path, "artifact_sha256 does not match canonical artifact hash"))
    if obj.get("artifact_hash") != obj.get("artifact_sha256"):
        errors.append(err(path, "artifact_hash must equal artifact_sha256"))
    _str(obj, "run_id", path, errors)
    _str(obj, "checked_at", path, errors)
    _str(obj, "target_model_id", path, errors)
    _str(obj, "prompt_sha256", path, errors)
    if not isinstance(obj.get("model_artifact"), dict):
        errors.append(err(path, "model_artifact must be an object"))
    if not isinstance(obj.get("spark_reachability"), dict):
        errors.append(err(path, "spark_reachability must be an object"))
    attempts = obj.get("runtime_attempts")
    if not isinstance(attempts, list) or len(attempts) == 0:
        errors.append(err(path, "runtime_attempts must be a non-empty list"))
    else:
        seen = set()
        for i, item in enumerate(attempts):
            if not isinstance(item, dict):
                errors.append(err(path, f"runtime_attempts[{i}] must be an object"))
                continue
            seen.add(item.get("runtime"))
            errors.extend(validate_attempt(item, path, i))
        missing = RUNTIMES.difference(seen)
        if missing:
            errors.append(err(path, "missing runtime attempt(s): " + ",".join(sorted(missing))))
    if not isinstance(obj.get("summary"), dict):
        errors.append(err(path, "summary must be an object"))
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
    parser.add_argument("artifacts", nargs="*", help="Artifact paths. Defaults to fixtures/external_mtp_runtime_bench/*.json.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = [Path(item) for item in args.artifacts] if args.artifacts else default_paths()
    result = validate_paths(paths)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"ok: validated {result['artifact_count']} external MTP runtime benchmark artifact(s)")
    else:
        for item in result["errors"]:
            print(item)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
