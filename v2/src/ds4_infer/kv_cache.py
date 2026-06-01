from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PREFIX_CACHE_REF_FORMAT = "ds4-prefix-cache-ref-v1"
PREFIX_CACHE_REF_KIND = "prefix_text"
PREFIX_CACHE_RESOLUTION_FORMAT = "ds4-prefix-cache-resolution-v1"
KV_CACHE_DIRECTIVE_FORMAT = "ds4-kv-cache-directive-v1"
KV_CACHE_PLAN_FORMAT = "ds4-kv-cache-plan-v1"
KV_CACHE_BUNDLE_MEDIA_TYPE = "application/vnd.ds4.kv-cache-bundle"
DEFAULT_MAX_INLINE_BUNDLE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_REQUEST_BLOB_BYTES = 16 * 1024 * 1024 * 1024
DEFAULT_MAX_PULL_BYTES = 16 * 1024 * 1024 * 1024
LOAD_MODES = {"skip", "prefer", "require"}
STORE_MODES = {"skip", "write_through", "write_back"}
LOAD_TRANSPORTS = {"inline", "request_blob", "remote_uri", "local_store"}
STORE_TRANSPORTS = {"remote_uri", "local_store"}
BACKENDS = {"auto", "apc_prefix", "lmcache", "simple_cpu_offload", "dsv4_hma"}
MISS_POLICIES = {"fail", "compute", "compute_and_store"}
ROUTE_AFFINITIES = {"none", "preferred", "required"}
REMOTE_URI_SCHEMES = {"http", "https", "ds4-kv", "lmcache", "s3"}


def resolve_request_cache_refs(data: dict[str, Any], *, base_dir: str | Path) -> dict[str, Any]:
    raw = dict(data)
    input_data = dict(raw.get("input", {}))
    _resolve_prefix_cache_ref(input_data, base_dir=Path(base_dir))
    _resolve_kv_cache_directive(input_data)
    raw["input"] = input_data
    return raw


def normalize_kv_cache_directive(directive: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(directive, dict):
        raise ValueError("input.kv_cache must be an object")
    if directive.get("format") != KV_CACHE_DIRECTIVE_FORMAT:
        raise ValueError(f"unsupported kv_cache format: {directive.get('format')!r}")
    cache_id = _optional_nonempty_str(directive, "cache_id")
    prefix_hash = _optional_nonempty_str(directive, "prefix_hash")
    if cache_id is None and prefix_hash is None:
        raise ValueError("input.kv_cache needs cache_id or prefix_hash")
    backend = _enum_value(directive, "backend", BACKENDS, default="auto")
    load = _normalize_load(directive.get("load"))
    store = _normalize_store(directive.get("store"))
    if load["mode"] == "skip" and store["mode"] == "skip":
        raise ValueError("input.kv_cache must load, store, or both")
    miss_policy = _enum_value(
        directive,
        "miss_policy",
        MISS_POLICIES,
        default=_default_miss_policy(load["mode"], store["mode"]),
    )
    route_affinity = _enum_value(
        directive,
        "route_affinity",
        ROUTE_AFFINITIES,
        default="required" if load.get("transport") == "local_store" else "none",
    )
    model_fingerprint = directive.get("model_fingerprint", {})
    if model_fingerprint is not None and not isinstance(model_fingerprint, dict):
        raise ValueError("input.kv_cache.model_fingerprint must be an object")
    plan = {
        "format": KV_CACHE_PLAN_FORMAT,
        "backend": backend,
        "cache_id": cache_id,
        "prefix_hash": prefix_hash,
        "load": load,
        "store": store,
        "miss_policy": miss_policy,
        "route_affinity": route_affinity,
        "model_fingerprint": dict(model_fingerprint or {}),
    }
    plan["operation"] = _operation(load, store)
    plan["batch_key_hash"] = "sha256:" + _sha256_json(_batch_key_material(plan))
    return plan


def request_kv_cache_batch_key(input_data: dict[str, Any]) -> str | None:
    plan = input_data.get("kv_cache_plan")
    if not isinstance(plan, dict):
        return None
    value = plan.get("batch_key_hash")
    return str(value) if value else None


def kv_cache_extra_body(input_data: dict[str, Any]) -> dict[str, Any]:
    plan = input_data.get("kv_cache_plan")
    if not isinstance(plan, dict):
        return {}
    return {"ds4_kv_cache": plan}


def kv_cache_vllm_request_fields(input_data: dict[str, Any]) -> dict[str, Any]:
    plan = input_data.get("kv_cache_plan")
    if not isinstance(plan, dict):
        return {}
    return {"kv_transfer_params": _kv_transfer_params(plan)}


def _resolve_prefix_cache_ref(input_data: dict[str, Any], *, base_dir: Path) -> None:
    ref = input_data.get("kv_cache_ref")
    if ref is None:
        return
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


def _resolve_kv_cache_directive(input_data: dict[str, Any]) -> None:
    directive = input_data.get("kv_cache")
    if directive is None:
        input_data.pop("kv_cache", None)
        return
    plan = normalize_kv_cache_directive(directive)
    existing = input_data.get("kv_cache_plan")
    if existing is not None and existing != plan:
        raise ValueError("input.kv_cache_plan conflicts with input.kv_cache")
    input_data["kv_cache_plan"] = plan


def _kv_transfer_params(plan: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "ds4_kv_cache": dict(plan),
        "ds4_require_kv_transfer": True,
    }
    cache_ref = _kv_cache_ref(plan)
    if cache_ref is not None:
        params["cache_ref"] = cache_ref
        params["ds4_cache_ref"] = cache_ref
        params["simple_kv_cache_ref"] = cache_ref
    return params


def _kv_cache_ref(plan: dict[str, Any]) -> str | None:
    for key in ("cache_id", "prefix_hash"):
        value = plan.get(key)
        if isinstance(value, str) and value:
            return value
    load = plan.get("load")
    if isinstance(load, dict):
        for key in ("cache_key", "kv_key"):
            value = load.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def ensure_cache_refs_resolved(input_data: dict[str, Any]) -> None:
    if "kv_cache_ref" not in input_data:
        pass
    elif not isinstance(input_data.get("shared_prefix"), str):
        raise ValueError("input.kv_cache_ref must be resolved before queueing")
    elif not isinstance(input_data.get("shared_prefix_hash"), str):
        raise ValueError("resolved input.kv_cache_ref must set shared_prefix_hash")
    if "kv_cache" in input_data and not isinstance(input_data.get("kv_cache_plan"), dict):
        raise ValueError("input.kv_cache must be resolved before queueing")
    if isinstance(input_data.get("kv_cache_plan"), dict):
        if input_data["kv_cache_plan"].get("format") != KV_CACHE_PLAN_FORMAT:
            raise ValueError("resolved input.kv_cache_plan has unsupported format")


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


def _normalize_load(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"mode": "skip", "transport": "none"}
    if not isinstance(raw, dict):
        raise ValueError("input.kv_cache.load must be an object")
    mode = _enum_value(raw, "mode", LOAD_MODES, default="prefer")
    if mode == "skip":
        return {"mode": "skip", "transport": "none"}
    transport = _enum_value(raw, "transport", LOAD_TRANSPORTS, default=None)
    source = _normalize_endpoint(raw, transport=transport, load=True)
    return dict({"mode": mode, "transport": transport}, **source)


def _normalize_store(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {"mode": "skip", "transport": "none"}
    if not isinstance(raw, dict):
        raise ValueError("input.kv_cache.store must be an object")
    mode = _enum_value(raw, "mode", STORE_MODES, default="skip")
    if mode == "skip":
        return {"mode": "skip", "transport": "none"}
    transport = _enum_value(raw, "transport", STORE_TRANSPORTS, default=None)
    target = _normalize_endpoint(raw, transport=transport, load=False)
    on_error = _enum_value(raw, "on_error", {"fail", "warn"}, default="fail")
    return dict({"mode": mode, "transport": transport, "on_error": on_error}, **target)


def _normalize_endpoint(raw: dict[str, Any], *, transport: str, load: bool) -> dict[str, Any]:
    if transport == "inline":
        if not load:
            raise ValueError("inline KV cache transport is load-only")
        return _normalize_inline_bundle(raw)
    if transport == "request_blob":
        if not load:
            raise ValueError("request_blob KV cache transport is load-only")
        return _normalize_request_blob(raw)
    if transport == "remote_uri":
        return _normalize_remote_uri(raw, load=load)
    if transport == "local_store":
        return _normalize_local_store(raw, load=load)
    raise ValueError(f"unsupported KV cache transport: {transport!r}")


def _normalize_inline_bundle(raw: dict[str, Any]) -> dict[str, Any]:
    claimed_bytes = _required_nonnegative_int(raw, "bytes")
    max_bytes = _max_bytes(raw, "max_inline_bytes", "DS4_KV_CACHE_MAX_INLINE_BUNDLE_BYTES", DEFAULT_MAX_INLINE_BUNDLE_BYTES)
    if claimed_bytes > max_bytes:
        raise ValueError(f"inline KV cache bundle exceeds max_inline_bytes: {claimed_bytes} > {max_bytes}")
    data_b64 = _required_nonempty_str(raw, "data_b64")
    _guard_base64_length(data_b64, max_bytes)
    sha256 = _required_sha256_value(raw)
    try:
        data = base64.b64decode(data_b64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise ValueError("inline KV cache bundle data_b64 is invalid base64") from exc
    if len(data) != claimed_bytes:
        raise ValueError(f"inline KV cache bundle bytes mismatch: declared {claimed_bytes}, decoded {len(data)}")
    if len(data) > max_bytes:
        raise ValueError(f"decoded inline KV cache bundle exceeds max_inline_bytes: {len(data)} > {max_bytes}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256.removeprefix("sha256:"):
        raise ValueError("inline KV cache bundle sha256 mismatch")
    return {
        "media_type": str(raw.get("media_type") or KV_CACHE_BUNDLE_MEDIA_TYPE),
        "bytes": claimed_bytes,
        "sha256": "sha256:" + digest,
        "data_b64": data_b64,
    }


def _normalize_request_blob(raw: dict[str, Any]) -> dict[str, Any]:
    claimed_bytes = _required_nonnegative_int(raw, "bytes")
    max_bytes = _max_bytes(raw, "max_request_blob_bytes", "DS4_KV_CACHE_MAX_REQUEST_BLOB_BYTES", DEFAULT_MAX_REQUEST_BLOB_BYTES)
    if claimed_bytes > max_bytes:
        raise ValueError(f"request KV cache blob exceeds max_request_blob_bytes: {claimed_bytes} > {max_bytes}")
    return {
        "blob_id": _required_nonempty_str(raw, "blob_id"),
        "bytes": claimed_bytes,
        "sha256": _required_sha256_value(raw),
        "media_type": str(raw.get("media_type") or KV_CACHE_BUNDLE_MEDIA_TYPE),
    }


def _normalize_remote_uri(raw: dict[str, Any], *, load: bool) -> dict[str, Any]:
    uri = _required_nonempty_str(raw, "uri")
    parsed = urlparse(uri)
    if parsed.scheme not in REMOTE_URI_SCHEMES:
        raise ValueError(f"remote KV cache uri has unsupported scheme: {parsed.scheme!r}")
    out: dict[str, Any] = {"uri": uri}
    if "bytes" in raw:
        claimed_bytes = _required_nonnegative_int(raw, "bytes")
        max_bytes = _max_bytes(raw, "max_pull_bytes", "DS4_KV_CACHE_MAX_PULL_BYTES", DEFAULT_MAX_PULL_BYTES)
        if claimed_bytes > max_bytes:
            raise ValueError(f"remote KV cache bundle exceeds max_pull_bytes: {claimed_bytes} > {max_bytes}")
        out["bytes"] = claimed_bytes
    if "sha256" in raw:
        out["sha256"] = _required_sha256_value(raw)
    elif load:
        raise ValueError("remote KV cache load requires sha256")
    return out


def _normalize_local_store(raw: dict[str, Any], *, load: bool) -> dict[str, Any]:
    out: dict[str, Any] = {"cache_key": _required_nonempty_str(raw, "cache_key")}
    if "bytes" in raw:
        out["bytes"] = _required_nonnegative_int(raw, "bytes")
    if "sha256" in raw:
        out["sha256"] = _required_sha256_value(raw)
    elif load:
        raise ValueError("local KV cache load requires sha256")
    return out


def _operation(load: dict[str, Any], store: dict[str, Any]) -> str:
    if load["mode"] != "skip" and store["mode"] != "skip":
        return "load_store"
    if load["mode"] != "skip":
        return "load"
    return "store"


def _default_miss_policy(load_mode: str, store_mode: str) -> str:
    if load_mode == "require":
        return "fail"
    if load_mode != "skip":
        return "compute"
    return "compute_and_store" if store_mode != "skip" else "compute"


def _batch_key_material(plan: dict[str, Any]) -> dict[str, Any]:
    load = dict(plan["load"])
    load.pop("data_b64", None)
    return {
        "backend": plan["backend"],
        "cache_id": plan.get("cache_id"),
        "prefix_hash": plan.get("prefix_hash"),
        "load": load,
        "store": plan["store"],
        "miss_policy": plan["miss_policy"],
        "route_affinity": plan["route_affinity"],
        "model_fingerprint": plan["model_fingerprint"],
    }


def _enum_value(data: dict[str, Any], key: str, allowed: set[str], *, default: str | None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"input.kv_cache.{key} must be one of {sorted(allowed)}")
    return value


def _optional_nonempty_str(data: dict[str, Any], key: str) -> str | None:
    if key not in data or data.get(key) is None:
        return None
    return _required_nonempty_str(data, key)


def _required_nonempty_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"input.kv_cache.{key} is required")
    return value


def _required_nonnegative_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool):
        raise ValueError(f"input.kv_cache.{key} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"input.kv_cache.{key} must be a non-negative integer") from exc
    if number < 0:
        raise ValueError(f"input.kv_cache.{key} must be a non-negative integer")
    return number


def _required_sha256_value(data: dict[str, Any]) -> str:
    value = _required_nonempty_str(data, "sha256")
    digest = value.removeprefix("sha256:")
    if len(digest) != 64:
        raise ValueError("input.kv_cache.sha256 must be a sha256 digest")
    try:
        bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError("input.kv_cache.sha256 must be a sha256 digest") from exc
    return "sha256:" + digest


def _max_bytes(data: dict[str, Any], key: str, env_name: str, default: int) -> int:
    raw = data.get(key, os.environ.get(env_name, default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"input.kv_cache.{key} must be an integer") from exc
    if value < 1:
        raise ValueError(f"input.kv_cache.{key} must be positive")
    return value


def _guard_base64_length(data_b64: str, max_bytes: int) -> None:
    max_encoded = ((max_bytes + 2) // 3) * 4
    if len(data_b64) > (max_encoded + 4):
        raise ValueError("inline KV cache bundle base64 exceeds max_inline_bytes before decode")


def _sha256_json(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
