#!/usr/bin/env python3
"""Validate ds4-vllm-pp-safetensors-filter-v1 artifacts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


FORMAT = "ds4-vllm-pp-safetensors-filter-v1"
HASH_FIELDS = {"artifact_sha256", "artifact_hash"}
REQUIRED_FIELDS = (
    "format",
    "artifact_sha256",
    "artifact_hash",
    "run_id",
    "checked_at",
    "model_id",
    "model_dir",
    "checkpoint_bytes",
    "checkpoint_gib",
    "files",
    "tensor_count",
    "pp_partition",
    "layer_ranges",
    "current_iterator_materializes_before_pp_skip",
    "early_filter_can_skip_before_tensor_load",
    "skip_is_conservative_floor",
    "rank_stats",
    "recommended_patch",
)
RANK_STAT_FIELDS = (
    "rank",
    "layer_start",
    "layer_end_exclusive",
    "total_seen_bytes",
    "local_layer_bytes",
    "local_layer_tensors",
    "skipped_layer_bytes",
    "skipped_layer_tensors",
    "mtp_skipped_bytes",
    "mtp_skipped_tensors",
    "global_or_rank_specific_bytes",
    "global_or_rank_specific_tensors",
    "candidate_materialized_bytes_without_filter",
    "candidate_materialized_bytes_with_early_filter_floor",
    "avoidable_tensor_load_bytes_floor",
    "avoidable_tensor_load_gib_floor",
    "avoidable_fraction_floor",
)


def default_paths() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    return sorted((root / "fixtures" / "vllm_pp_safetensors_filter").glob("*.json"))


def err(path: Path, msg: str) -> str:
    return f"{path}: {msg}"


def canonical_hash(obj: dict[str, Any]) -> str:
    payload = copy.deepcopy(obj)
    for field in HASH_FIELDS:
        payload.pop(field, None)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


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


def validate_rank_stat(obj: dict[str, Any], path: Path, checkpoint_bytes: int) -> list[str]:
    errors: list[str] = []
    for field in RANK_STAT_FIELDS:
        if field not in obj:
            errors.append(err(path, f"missing required rank stat field: {field}"))
    for field in RANK_STAT_FIELDS:
        if field in {"rank", "layer_start", "layer_end_exclusive"}:
            value = obj.get(field)
            if not isinstance(value, int) or value < 0:
                errors.append(err(path, f"{field} must be a non-negative integer"))
        elif field in obj:
            _num(obj, field, path, errors)
    start = obj.get("layer_start")
    end = obj.get("layer_end_exclusive")
    if isinstance(start, int) and isinstance(end, int) and end <= start:
        errors.append(err(path, "layer_end_exclusive must be greater than layer_start"))
    total_seen = obj.get("total_seen_bytes")
    if total_seen != checkpoint_bytes:
        errors.append(err(path, "total_seen_bytes must equal checkpoint_bytes"))
    local = obj.get("local_layer_bytes", 0)
    skipped = obj.get("skipped_layer_bytes", 0)
    mtp = obj.get("mtp_skipped_bytes", 0)
    global_bytes = obj.get("global_or_rank_specific_bytes", 0)
    if all(isinstance(item, int) for item in (local, skipped, mtp, global_bytes)):
        if local + skipped + mtp + global_bytes != checkpoint_bytes:
            errors.append(err(path, "rank byte categories must sum to checkpoint_bytes"))
        without_filter = obj.get("candidate_materialized_bytes_without_filter")
        with_filter = obj.get("candidate_materialized_bytes_with_early_filter_floor")
        avoidable = obj.get("avoidable_tensor_load_bytes_floor")
        if without_filter != checkpoint_bytes:
            errors.append(err(path, "candidate_materialized_bytes_without_filter must equal checkpoint_bytes"))
        if with_filter != local + global_bytes:
            errors.append(err(path, "candidate_materialized_bytes_with_early_filter_floor must equal local_layer_bytes + global_or_rank_specific_bytes"))
        if avoidable != skipped + mtp:
            errors.append(err(path, "avoidable_tensor_load_bytes_floor must equal skipped_layer_bytes + mtp_skipped_bytes"))
        fraction = obj.get("avoidable_fraction_floor")
        if isinstance(fraction, (int, float)) and checkpoint_bytes > 0:
            expected = avoidable / checkpoint_bytes
            if abs(float(fraction) - expected) > 0.000001:
                errors.append(err(path, "avoidable_fraction_floor must equal avoidable/checkpoint_bytes"))
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
    _str(obj, "model_id", path, errors)
    _str(obj, "model_dir", path, errors)
    checkpoint = int(_num(obj, "checkpoint_bytes", path, errors, positive=True))
    _num(obj, "checkpoint_gib", path, errors, positive=True)
    _num(obj, "files", path, errors, positive=True)
    _num(obj, "tensor_count", path, errors, positive=True)
    partition = obj.get("pp_partition")
    if not isinstance(partition, list) or len(partition) == 0 or not all(isinstance(item, int) and item > 0 for item in partition):
        errors.append(err(path, "pp_partition must be a non-empty list of positive integers"))
    rank_stats = obj.get("rank_stats")
    if not isinstance(rank_stats, list) or len(rank_stats) == 0:
        errors.append(err(path, "rank_stats must be a non-empty list"))
    elif isinstance(partition, list) and len(rank_stats) != len(partition):
        errors.append(err(path, "rank_stats length must equal pp_partition length"))
    elif isinstance(rank_stats, list):
        for idx, item in enumerate(rank_stats):
            if not isinstance(item, dict):
                errors.append(err(path, f"rank_stats[{idx}] must be an object"))
                continue
            errors.extend(validate_rank_stat(item, Path(f"{path}#rank_stats[{idx}]"), checkpoint))
    if obj.get("current_iterator_materializes_before_pp_skip") is not True:
        errors.append(err(path, "current_iterator_materializes_before_pp_skip must be true"))
    if obj.get("early_filter_can_skip_before_tensor_load") is not True:
        errors.append(err(path, "early_filter_can_skip_before_tensor_load must be true"))
    if obj.get("skip_is_conservative_floor") is not True:
        errors.append(err(path, "skip_is_conservative_floor must be true"))
    if not isinstance(obj.get("recommended_patch"), dict):
        errors.append(err(path, "recommended_patch must be an object"))
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
    parser.add_argument("artifacts", nargs="*", help="Artifact paths. Defaults to fixtures/vllm_pp_safetensors_filter/*.json.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = [Path(item) for item in args.artifacts] if args.artifacts else default_paths()
    result = validate_paths(paths)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif result["ok"]:
        print(f"ok: validated {result['artifact_count']} vLLM PP safetensors filter artifact(s)")
    else:
        for item in result["errors"]:
            print(item)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
