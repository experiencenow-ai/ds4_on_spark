#!/usr/bin/env python3
"""Validate DS4 SGLang provider probe artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-sglang-provider-probe-v1"
PROVIDER_RECIPES = {"low_latency", "balanced", "max_throughput", "custom"}
OUTPUT_MODES = {"full_vocab", "constrained_structured"}
CASE_STATUSES = {"success", "blocked", "not_run", "unsupported"}
CONSTRAINED_SCORING = {"candidate_only", "full_vocab_mask", "unknown", "unsupported"}
CHECKPOINT_SOURCE_KINDS = {"huggingface", "local_path", "gguf_custom_path", "unknown"}
CHECKPOINT_SOURCE_STATUSES = {"available", "blocked", "missing", "not_checked"}
API_HEALTH_STATUSES = {"success", "failed", "blocked", "not_run"}
BLOCKER_KINDS = {
    "none",
    "sglang_not_installed",
    "model_checkpoint_missing",
    "missing_hf_token",
    "checkpoint_unavailable",
    "insufficient_disk",
    "insufficient_memory",
    "unsupported_gpu",
    "host_unreachable",
    "spark_reachability_blocked",
    "runtime_install_failed",
    "dependency_conflict",
    "launch_not_run_requires_explicit_allow_launch",
    "launch_failed",
    "api_health_failed",
    "benchmark_not_run",
    "unsupported_constrained_output",
    "other",
    "unknown",
}
FIXED_SPARK_COUNT_FIELDS = {"spark_count", "num_sparks", "world_size"}
REQUIRED_FIELDS = (
    "format",
    "provider_id",
    "model_id",
    "checkpoint_format",
    "checkpoint_source",
    "runtime_id",
    "sglang_version",
    "hardware",
    "launch_command",
    "recipe",
    "mtp_enabled",
    "mtp_settings",
    "max_running_requests",
    "tp_size",
    "pp_size",
    "dp_size",
    "memory_used_gib",
    "load_success",
    "api_health_status",
    "benchmark_results",
    "blocker_kind",
    "blocker_detail",
)
REQUIRED_CASES = {
    "b1_full_vocab_chat",
    "b4_q_numbered_full_vocab_rows",
    "b16_full_vocab_rows",
    "b512_full_vocab_one_token",
    "b512_constrained_structured_output",
    "mtp_low_latency",
    "mtp_balanced",
    "max_throughput_mtp_disabled",
}


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_obj(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def artifact_sha256(obj: dict[str, Any]) -> str:
    tmp = copy.deepcopy(obj)
    tmp.pop("artifact_sha256", None)
    tmp.pop("artifact_hash", None)
    return sha256_obj(tmp)


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"{path}: root JSON must be an object")
    return obj


def _err(errors: list[str], msg: str) -> None:
    errors.append(msg)


def _string(obj: dict[str, Any], key: str, errors: list[str], allow_empty: bool = False) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        _err(errors, f"{key} must be a non-empty string")
        return ""
    return value.strip()


def _nonnegative_number(obj: dict[str, Any], key: str, errors: list[str], allow_null: bool = False) -> float | None:
    value = obj.get(key)
    if value is None and allow_null:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < 0.0:
        _err(errors, f"{key} must be a non-negative number")
        return None
    return float(value)


def _positive_int(obj: dict[str, Any], key: str, errors: list[str]) -> int:
    value = obj.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _err(errors, f"{key} must be a positive integer")
        return 0
    return int(value)


def validate_benchmark_case(case: dict[str, Any], errors: list[str]) -> None:
    case_id = _string(case, "case_id", errors)
    status = _string(case, "status", errors)
    if status and status not in CASE_STATUSES:
        _err(errors, f"{case_id}.status is invalid")
    batch_size = _positive_int(case, "batch_size", errors)
    output_mode = _string(case, "output_mode", errors)
    recipe = _string(case, "recipe", errors)
    if output_mode and output_mode not in OUTPUT_MODES:
        _err(errors, f"{case_id}.output_mode is invalid")
    if recipe and recipe not in PROVIDER_RECIPES:
        _err(errors, f"{case_id}.recipe is invalid")
    if not isinstance(case.get("mtp_enabled"), bool):
        _err(errors, f"{case_id}.mtp_enabled must be a bool")
    if not isinstance(case.get("tokens_per_second"), (int, float, type(None))) or isinstance(case.get("tokens_per_second"), bool):
        _err(errors, f"{case_id}.tokens_per_second must be a number or null")
    if not isinstance(case.get("latency_ms"), (int, float, type(None))) or isinstance(case.get("latency_ms"), bool):
        _err(errors, f"{case_id}.latency_ms must be a number or null")
    scoring = _string(case, "constrained_scoring", errors)
    if scoring and scoring not in CONSTRAINED_SCORING:
        _err(errors, f"{case_id}.constrained_scoring is invalid")
    if status == "success":
        if not isinstance(case.get("tokens_per_second"), (int, float)) or float(case["tokens_per_second"]) <= 0.0:
            _err(errors, f"{case_id} success requires positive tokens_per_second")
        if scoring == "unknown":
            _err(errors, f"{case_id} must not claim speed with unknown constrained scoring")
    else:
        if case.get("tokens_per_second") not in (None, 0, 0.0):
            _err(errors, f"{case_id} blocked/not_run rows must not report tokens_per_second")
    if case_id == "b512_constrained_structured_output" and scoring == "unknown" and case.get("custom_ds4_speedup_inferred") is True:
        _err(errors, "constrained output speedup must not be inferred when SGLang scoring mode is unknown")
    if case_id == "b1_full_vocab_chat" and batch_size != 1:
        _err(errors, "b1_full_vocab_chat batch_size must be 1")
    if case_id == "b4_q_numbered_full_vocab_rows" and batch_size != 4:
        _err(errors, "b4_q_numbered_full_vocab_rows batch_size must be 4")
    if case_id == "b16_full_vocab_rows" and batch_size != 16:
        _err(errors, "b16_full_vocab_rows batch_size must be 16")
    if case_id.startswith("b512_") and batch_size != 512:
        _err(errors, f"{case_id} batch_size must be 512")


def validate_checkpoint_source(source: Any, errors: list[str]) -> None:
    if not isinstance(source, dict):
        _err(errors, "checkpoint_source must be an object")
        return
    kind = _string(source, "kind", errors)
    status = _string(source, "status", errors)
    if kind and kind not in CHECKPOINT_SOURCE_KINDS:
        _err(errors, "checkpoint_source.kind is invalid")
    if status and status not in CHECKPOINT_SOURCE_STATUSES:
        _err(errors, "checkpoint_source.status is invalid")
    if "repo_id" in source and not isinstance(source["repo_id"], str):
        _err(errors, "checkpoint_source.repo_id must be a string when present")
    if "local_path" in source and not isinstance(source["local_path"], str):
        _err(errors, "checkpoint_source.local_path must be a string when present")
    if "hf_token_present" in source and not isinstance(source["hf_token_present"], bool):
        _err(errors, "checkpoint_source.hf_token_present must be a bool when present")
    if status in {"blocked", "missing"} and not isinstance(source.get("detail"), str):
        _err(errors, "checkpoint_source blocked/missing requires detail")


def validate_api_health_status(status_obj: Any, errors: list[str]) -> None:
    if not isinstance(status_obj, dict):
        _err(errors, "api_health_status must be an object")
        return
    status = _string(status_obj, "status", errors)
    if status and status not in API_HEALTH_STATUSES:
        _err(errors, "api_health_status.status is invalid")
    if "endpoint" in status_obj and not isinstance(status_obj["endpoint"], str):
        _err(errors, "api_health_status.endpoint must be a string when present")
    for key in ("http_status", "latency_ms", "output_token_count"):
        value = status_obj.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) < 0.0):
            _err(errors, f"api_health_status.{key} must be a non-negative number or null")
    if "response_hash" in status_obj and status_obj["response_hash"] is not None and not isinstance(status_obj["response_hash"], str):
        _err(errors, "api_health_status.response_hash must be a string or null when present")
    if status in {"failed", "blocked"} and not isinstance(status_obj.get("error"), str):
        _err(errors, "api_health_status failed/blocked requires error")


def validate_acquisition_attempts(attempts: Any, errors: list[str]) -> None:
    if attempts is None:
        return
    if not isinstance(attempts, list):
        _err(errors, "acquisition_attempts must be a list when present")
        return
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            _err(errors, f"acquisition_attempts[{index}] must be an object")
            continue
        _string(attempt, "step", errors)
        _string(attempt, "status", errors)
        command = attempt.get("command")
        if command is not None and (not isinstance(command, list) or not all(isinstance(item, str) for item in command)):
            _err(errors, f"acquisition_attempts[{index}].command must be a list of strings when present")
        if "error" in attempt and not isinstance(attempt["error"], str):
            _err(errors, f"acquisition_attempts[{index}].error must be a string when present")


def validate_artifact_ref(ref: Any, key: str, errors: list[str]) -> None:
    if ref is None:
        return
    if not isinstance(ref, dict):
        _err(errors, f"{key} must be an object when present")
        return
    for field in ("path", "sha256", "format"):
        if not isinstance(ref.get(field), str) or not ref[field].strip():
            _err(errors, f"{key}.{field} must be a non-empty string")


def validate_probe(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in obj:
            _err(errors, f"missing required field: {field}")
    for field in FIXED_SPARK_COUNT_FIELDS:
        if field in obj:
            _err(errors, f"fixed Spark count field is not allowed: {field}")
    if obj.get("format") != FORMAT:
        _err(errors, f"format must be {FORMAT}")
    for key in ("provider_id", "model_id", "checkpoint_format", "runtime_id", "sglang_version", "blocker_kind"):
        _string(obj, key, errors)
    validate_checkpoint_source(obj.get("checkpoint_source"), errors)
    if obj.get("recipe") not in PROVIDER_RECIPES:
        _err(errors, "recipe is invalid")
    if obj.get("blocker_kind") not in BLOCKER_KINDS:
        _err(errors, "blocker_kind is invalid")
    if not isinstance(obj.get("hardware"), dict):
        _err(errors, "hardware must be an object")
    if not isinstance(obj.get("launch_command"), list) or not all(isinstance(item, str) and item for item in obj.get("launch_command", [])):
        _err(errors, "launch_command must be a non-empty list of strings")
    if not isinstance(obj.get("mtp_enabled"), bool):
        _err(errors, "mtp_enabled must be a bool")
    if not isinstance(obj.get("mtp_settings"), dict):
        _err(errors, "mtp_settings must be an object")
    for key in ("max_running_requests", "tp_size", "pp_size", "dp_size"):
        _positive_int(obj, key, errors)
    _nonnegative_number(obj, "memory_used_gib", errors, allow_null=True)
    if not isinstance(obj.get("load_success"), bool):
        _err(errors, "load_success must be a bool")
    validate_api_health_status(obj.get("api_health_status"), errors)
    validate_acquisition_attempts(obj.get("acquisition_attempts"), errors)
    validate_artifact_ref(obj.get("reachability_report_ref"), "reachability_report_ref", errors)
    if not isinstance(obj.get("benchmark_results"), list):
        _err(errors, "benchmark_results must be a list")
    else:
        seen = set()
        for case in obj["benchmark_results"]:
            if not isinstance(case, dict):
                _err(errors, "benchmark_results entries must be objects")
                continue
            seen.add(str(case.get("case_id")))
            validate_benchmark_case(case, errors)
        missing = REQUIRED_CASES - seen
        if missing:
            _err(errors, "missing benchmark case(s): " + ", ".join(sorted(missing)))
    if obj.get("load_success") is False:
        if obj.get("blocker_kind") in ("none", "", None):
            _err(errors, "load_success=false requires blocker_kind")
        if not isinstance(obj.get("blocker_detail"), str) or not obj.get("blocker_detail", "").strip():
            _err(errors, "load_success=false requires blocker_detail")
    if "custom_ds4_comparison" in obj:
        if not isinstance(obj["custom_ds4_comparison"], dict):
            _err(errors, "custom_ds4_comparison must be an object")
        else:
            for key in ("custom_ds4_constrained_b512", "custom_ds4_full_vocab_b512", "custom_ds4_mtp_k2"):
                if key not in obj["custom_ds4_comparison"]:
                    _err(errors, f"custom_ds4_comparison missing {key}")
    if "launch_environment" in obj and not isinstance(obj["launch_environment"], dict):
        _err(errors, "launch_environment must be an object")
    if "recommendation" in obj and obj["recommendation"] not in {"replace", "replace_candidate", "complement", "blocked", "retest"}:
        _err(errors, "recommendation is invalid")
    if obj.get("artifact_sha256") is not None and obj.get("artifact_sha256") != artifact_sha256(obj):
        _err(errors, "artifact_sha256 does not match canonical artifact body")
    if obj.get("artifact_hash") is not None and obj.get("artifact_hash") != obj.get("artifact_sha256"):
        _err(errors, "artifact_hash must match artifact_sha256")
    return errors


def validate_paths(paths: list[Path]) -> dict[str, Any]:
    errors: list[str] = []
    for path in paths:
        try:
            obj = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        for error in validate_probe(obj):
            errors.append(f"{path}: {error}")
    return {"ok": not errors, "artifact_count": len(paths), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate_paths([Path(item) for item in args.artifacts])
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"ok: validated {result['artifact_count']} SGLang provider probe artifact(s)")
    else:
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
