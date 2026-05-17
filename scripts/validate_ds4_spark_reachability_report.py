#!/usr/bin/env python3
"""Validate DS4 Spark reachability report artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-spark-reachability-report-v1"
REQUIRED_FIELDS = (
    "format",
    "run_id",
    "checked_at",
    "local_host",
    "expected_hosts",
    "dns_results",
    "mdns_results",
    "ping_results",
    "ssh_results",
    "known_hosts_status",
    "network_interface_summary",
    "blocker_kind",
    "blocker_detail",
    "recommended_fix",
)
BLOCKER_KINDS = {
    "none",
    "spark_host_resolution_unreachable",
    "ssh_unreachable",
    "partial_reachability",
    "no_expected_hosts",
    "unknown",
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


def _string(obj: dict[str, Any], key: str, errors: list[str]) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        _err(errors, f"{key} must be a non-empty string")
        return ""
    return value


def _result_map(obj: dict[str, Any], key: str, errors: list[str]) -> None:
    value = obj.get(key)
    if not isinstance(value, dict):
        _err(errors, f"{key} must be an object keyed by host")
        return
    for host, result in value.items():
        if not isinstance(host, str) or not host:
            _err(errors, f"{key} has an invalid host key")
        if not isinstance(result, dict):
            _err(errors, f"{key}.{host} must be an object")
            continue
        if not isinstance(result.get("status"), str) or not result["status"]:
            _err(errors, f"{key}.{host}.status must be a non-empty string")
        if "command" in result and not isinstance(result["command"], list):
            _err(errors, f"{key}.{host}.command must be a list when present")
        if "error" in result and result["error"] is not None and not isinstance(result["error"], str):
            _err(errors, f"{key}.{host}.error must be a string or null")


def validate_report(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in obj:
            _err(errors, f"missing required field: {field}")
    if obj.get("format") != FORMAT:
        _err(errors, f"format must be {FORMAT}")
    for key in ("run_id", "checked_at", "blocker_kind", "blocker_detail", "recommended_fix"):
        _string(obj, key, errors)
    if obj.get("blocker_kind") not in BLOCKER_KINDS:
        _err(errors, "blocker_kind is invalid")
    if not isinstance(obj.get("local_host"), dict):
        _err(errors, "local_host must be an object")
    expected = obj.get("expected_hosts")
    if not isinstance(expected, list) or not expected or not all(isinstance(item, str) and item for item in expected):
        _err(errors, "expected_hosts must be a non-empty list of strings")
        expected = []
    for key in ("dns_results", "mdns_results", "ping_results", "ssh_results", "known_hosts_status"):
        _result_map(obj, key, errors)
        result_map = obj.get(key)
        if isinstance(result_map, dict):
            for host in expected:
                if host not in result_map:
                    _err(errors, f"{key} missing expected host: {host}")
    if not isinstance(obj.get("network_interface_summary"), dict):
        _err(errors, "network_interface_summary must be an object")
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
        for error in validate_report(obj):
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
        print(f"ok: validated {result['artifact_count']} Spark reachability report artifact(s)")
    else:
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
