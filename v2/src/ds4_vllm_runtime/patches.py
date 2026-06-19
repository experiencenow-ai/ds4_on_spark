"""Runtime patches used by DS4 vLLM launcher wrappers."""

from __future__ import annotations

import importlib
import os


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


def apply_runtime_patches() -> list[str]:
    patches = []
    if env_flag("DS4_VLLM_SM12_FLASHMLA_SPARSE"):
        patches.append(allow_sm12_flashmla_sparse())
    return patches

