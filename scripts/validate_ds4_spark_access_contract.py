#!/usr/bin/env python3
"""Validate DS4 Spark access contract artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-spark-access-contract-v1"
ACCESS_MODES = {"known_good_ssh", "repo_inventory", "direct_ip", "discovery_only"}
BLOCKER_KINDS = {"none", "known_good_ssh_failed", "spark_probe_failed", "repo_inventory_failed", "discovery_only_failed", "unknown"}
REQUIRED_FIELDS = (
    "format",
    "run_id",
    "checked_at",
    "access_mode",
    "targets_checked",
    "known_good_commands",
    "ssh_results",
    "probe_results",
    "discovery_results",
    "access_ok",
    "discovery_partial",
    "blocker_kind",
    "blocker_detail",
)


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
    return value


def _result_map(obj: dict[str, Any], key: str, errors: list[str]) -> None:
    value = obj.get(key)
    if not isinstance(value, dict):
        _err(errors, f"{key} must be an object")
        return
    for name, result in value.items():
        if not isinstance(name, str) or not name:
            _err(errors, f"{key} has an invalid key")
        if not isinstance(result, dict):
            _err(errors, f"{key}.{name} must be an object")
            continue
        if not isinstance(result.get("status"), str) or not result["status"]:
            _err(errors, f"{key}.{name}.status must be a non-empty string")
        if "command" in result and (not isinstance(result["command"], list) or not all(isinstance(item, str) for item in result["command"])):
            _err(errors, f"{key}.{name}.command must be a list of strings when present")
        if "env" in result and (not isinstance(result["env"], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in result["env"].items())):
            _err(errors, f"{key}.{name}.env must be an object of strings when present")
        if "error" in result and result["error"] is not None and not isinstance(result["error"], str):
            _err(errors, f"{key}.{name}.error must be a string or null")


def validate_contract(obj: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if field not in obj:
            _err(errors, f"missing required field: {field}")
    if obj.get("format") != FORMAT:
        _err(errors, f"format must be {FORMAT}")
    for key in ("run_id", "checked_at", "access_mode", "blocker_kind", "blocker_detail"):
        _string(obj, key, errors)
    if obj.get("access_mode") not in ACCESS_MODES:
        _err(errors, "access_mode is invalid")
    if obj.get("blocker_kind") not in BLOCKER_KINDS:
        _err(errors, "blocker_kind is invalid")
    targets = obj.get("targets_checked")
    if not isinstance(targets, list) or not targets or not all(isinstance(item, str) and item for item in targets):
        _err(errors, "targets_checked must be a non-empty list of strings")
    commands = obj.get("known_good_commands")
    if not isinstance(commands, list) or not commands:
        _err(errors, "known_good_commands must be a non-empty list")
    else:
        for index, command in enumerate(commands):
            if not isinstance(command, dict):
                _err(errors, f"known_good_commands[{index}] must be an object")
                continue
            _string(command, "label", errors)
            if not isinstance(command.get("command"), list) or not all(isinstance(item, str) for item in command.get("command", [])):
                _err(errors, f"known_good_commands[{index}].command must be a list of strings")
    _result_map(obj, "ssh_results", errors)
    _result_map(obj, "probe_results", errors)
    _result_map(obj, "discovery_results", errors)
    if not isinstance(obj.get("access_ok"), bool):
        _err(errors, "access_ok must be a bool")
    if not isinstance(obj.get("discovery_partial"), bool):
        _err(errors, "discovery_partial must be a bool")
    if obj.get("access_ok") is True and obj.get("blocker_kind") != "none":
        _err(errors, "access_ok=true requires blocker_kind=none")
    if obj.get("access_ok") is False and obj.get("blocker_kind") == "none":
        _err(errors, "access_ok=false requires a blocker")
    if isinstance(obj.get("ssh_results"), dict):
        first = obj["ssh_results"].get("spark0@aitopatom-9ab9.local")
        if not isinstance(first, dict):
            _err(errors, "ssh_results must include spark0@aitopatom-9ab9.local")
    if isinstance(obj.get("probe_results"), dict):
        first_probe = obj["probe_results"].get("spark_probe_aitopatom_9ab9_local")
        if not isinstance(first_probe, dict):
            _err(errors, "probe_results must include spark_probe_aitopatom_9ab9_local")
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
        for error in validate_contract(obj):
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
        print(f"ok: validated {result['artifact_count']} Spark access contract artifact(s)")
    else:
        for error in result["errors"]:
            print(f"error: {error}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
