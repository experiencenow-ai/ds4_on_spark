from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

PREFIX_CACHE_REF_FORMAT = "ds4-prefix-cache-ref-v1"
PREFIX_CACHE_REF_KIND = "prefix_text"
PREFIX_CACHE_RESOLUTION_FORMAT = "ds4-prefix-cache-resolution-v1"


def resolve_request_cache_refs(data: dict[str, Any], *, base_dir: str | Path) -> dict[str, Any]:
    raw = dict(data)
    input_data = dict(raw.get("input", {}))
    ref = input_data.get("kv_cache_ref")
    if ref is None:
        return raw
    if not isinstance(ref, dict):
        raise ValueError("input.kv_cache_ref must be an object")
    if ref.get("format") != PREFIX_CACHE_REF_FORMAT:
        raise ValueError(f"unsupported kv_cache_ref format: {ref.get('format')!r}")
    if ref.get("kind") != PREFIX_CACHE_REF_KIND:
        raise ValueError(f"unsupported kv_cache_ref kind: {ref.get('kind')!r}")
    path = _cache_path(ref, base_dir=Path(base_dir))
    data_bytes = path.read_bytes()
    digest = hashlib.sha256(data_bytes).hexdigest()
    expected = _required_sha256(ref)
    if digest != expected:
        raise ValueError(f"kv_cache_ref sha256 mismatch for {path}: expected {expected}, got {digest}")
    try:
        shared_prefix = data_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"kv_cache_ref prefix must be UTF-8 text: {path}") from exc
    existing = input_data.get("shared_prefix")
    if existing is not None and existing != shared_prefix:
        raise ValueError("input.shared_prefix conflicts with input.kv_cache_ref")
    shared_hash = "sha256:" + digest
    _set_or_verify(input_data, "shared_prefix_hash", shared_hash)
    skeleton_hash = ref.get("skeleton_hash") or input_data.get("skeleton_hash") or shared_hash
    _set_or_verify(input_data, "skeleton_hash", str(skeleton_hash))
    input_data["shared_prefix"] = shared_prefix
    input_data["kv_cache_resolution"] = {
        "format": PREFIX_CACHE_RESOLUTION_FORMAT,
        "kind": PREFIX_CACHE_REF_KIND,
        "path": str(path),
        "sha256": shared_hash,
        "bytes": len(data_bytes),
    }
    raw["input"] = input_data
    return raw


def ensure_cache_refs_resolved(input_data: dict[str, Any]) -> None:
    if "kv_cache_ref" not in input_data:
        return
    if not isinstance(input_data.get("shared_prefix"), str):
        raise ValueError("input.kv_cache_ref must be resolved before queueing")
    if not isinstance(input_data.get("shared_prefix_hash"), str):
        raise ValueError("resolved input.kv_cache_ref must set shared_prefix_hash")


def _cache_path(ref: dict[str, Any], *, base_dir: Path) -> Path:
    value = ref.get("path")
    if not isinstance(value, str) or not value:
        raise ValueError("input.kv_cache_ref.path is required")
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _required_sha256(ref: dict[str, Any]) -> str:
    value = ref.get("sha256")
    if not isinstance(value, str) or not value:
        raise ValueError("input.kv_cache_ref.sha256 is required")
    return value.removeprefix("sha256:")


def _set_or_verify(data: dict[str, Any], key: str, value: str) -> None:
    existing = data.get(key)
    if existing is not None and str(existing) != value:
        raise ValueError(f"input.{key} conflicts with input.kv_cache_ref")
    data[key] = value
