"""Runtime patches used by DS4 vLLM launcher wrappers."""

from __future__ import annotations

import importlib
import os
from typing import Any


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def allow_sm12_flashmla_sparse() -> str:
    flashmla_sparse = importlib.import_module(
        "vllm.v1.attention.backends.mla.flashmla_sparse"
    )

    @classmethod
    def supports_compute_capability(cls, capability):  # type: ignore[no-untyped-def]
        return capability.major in (9, 10, 12)

    flashmla_sparse.FlashMLASparseBackend.supports_compute_capability = (
        supports_compute_capability
    )
    return "flashmla_sparse_sm12_compute_capability"


def _configured_block_size(client: Any) -> int | None:
    vllm_config = getattr(client, "vllm_config", None)
    cache_config = getattr(vllm_config, "cache_config", None)
    block_size = getattr(cache_config, "block_size", None)
    if block_size is not None:
        return int(block_size)
    env_block_size = os.getenv("DS4_VLLM_READY_RESPONSE_BLOCK_SIZE", "")
    if env_block_size.strip() == "":
        return None
    return int(env_block_size)


def _configured_dtype(client: Any) -> str | None:
    vllm_config = getattr(client, "vllm_config", None)
    model_config = getattr(vllm_config, "model_config", None)
    dtype = getattr(model_config, "dtype", None)
    if dtype is None:
        return None
    return str(dtype).removeprefix("torch.")


def _current_vllm_version(core_client: Any) -> str:
    version = getattr(core_client, "VLLM_VERSION", None)
    if version is not None:
        return str(version)
    for module_name in ("vllm.version", "vllm"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for attr in ("VLLM_VERSION", "__version__", "VERSION"):
            version = getattr(module, attr, None)
            if version is not None:
                return str(version)
    return "unknown"


def _payload_has_key(data: dict[Any, Any], name: str) -> bool:
    return name in data or name.encode("utf-8") in data


def _payload_key_for(data: dict[Any, Any], name: str) -> str | bytes:
    if any(isinstance(k, bytes) for k in data):
        return name.encode("utf-8")
    return name


def _repair_ready_response_payload(
    msgspec_module: Any, payload: bytes, repairs: dict[str, Any]
) -> bytes | None:
    data = msgspec_module.msgpack.decode(payload)
    if not isinstance(data, dict):
        return None
    repaired = dict(data)
    changed = False
    for name, value in repairs.items():
        if _payload_has_key(repaired, name):
            continue
        repaired[_payload_key_for(repaired, name)] = value
        changed = True
    if not changed:
        return None
    return msgspec_module.msgpack.encode(repaired)


def allow_missing_ready_response_block_size() -> str:
    core_client = importlib.import_module("vllm.v1.engine.core_client")
    client_cls = getattr(core_client, "MPClient", None)
    if client_cls is None:
        return "ready_response_block_size_compat_unavailable"
    original = getattr(client_cls, "_apply_ready_response", None)
    if original is None:
        return "ready_response_block_size_compat_unavailable"
    if getattr(original, "_ds4_ready_response_block_size_compat", False):
        return "ready_response_block_size_compat"
    msgspec_module = getattr(core_client, "msgspec")
    validation_error = getattr(msgspec_module, "ValidationError")
    vllm_version = _current_vllm_version(core_client)

    def apply_ready_response(self, payload: bytes) -> None:  # type: ignore[no-untyped-def]
        try:
            return original(self, payload)
        except validation_error as exc:
            if "missing required field" not in str(exc):
                raise
            block_size = _configured_block_size(self)
            if block_size is None:
                raise
            dtype = _configured_dtype(self)
            if dtype is None:
                dtype = "unknown"
            repaired = _repair_ready_response_payload(
                msgspec_module,
                payload,
                {
                    "block_size": block_size,
                    "dp_stats_address": None,
                    "dtype": dtype,
                    "vllm_version": vllm_version,
                },
            )
            if repaired is None:
                raise
            return original(self, repaired)

    apply_ready_response._ds4_ready_response_block_size_compat = True  # type: ignore[attr-defined]
    client_cls._apply_ready_response = apply_ready_response
    return "ready_response_block_size_compat"


def apply_runtime_patches() -> list[str]:
    patches = []
    if env_flag("DS4_VLLM_READY_RESPONSE_COMPAT"):
        patches.append(allow_missing_ready_response_block_size())
    if env_flag("DS4_VLLM_SM12_FLASHMLA_SPARSE"):
        patches.append(allow_sm12_flashmla_sparse())
    return patches
