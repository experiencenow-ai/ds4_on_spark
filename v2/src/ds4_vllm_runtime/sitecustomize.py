"""Child-process startup hook for DS4 vLLM runtime patches."""

from __future__ import annotations

import os
import sys


def _enabled() -> bool:
    value = os.getenv("DS4_VLLM_SM12_FLASHMLA_SPARSE", "")
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _strict() -> bool:
    value = os.getenv("DS4_VLLM_RUNTIME_PATCHES_STRICT", "")
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


if _enabled():
    try:
        from ds4_vllm_runtime.patches import apply_runtime_patches

        apply_runtime_patches()
    except Exception as exc:
        print(f"DS4 vLLM runtime patch failed: {exc}", file=sys.stderr)
        if _strict():
            raise

