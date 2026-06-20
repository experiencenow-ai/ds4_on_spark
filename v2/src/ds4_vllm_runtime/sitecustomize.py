"""Child-process startup hook for DS4 vLLM runtime patches."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def _enabled() -> bool:
    for name in (
        "DS4_VLLM_SM12_FLASHINFER_MLA_SPARSE",
        "DS4_VLLM_SM12_FLASHMLA_SPARSE",
        "DS4_VLLM_FLASHMLA_SPARSE_TORCH_FALLBACK",
        "DS4_VLLM_SM12_SPARSE_INDEXER_DENSE_FALLBACK",
        "DS4_VLLM_FLASHINFER_MLA_SHARED_BLOCK_TABLES_2D",
        "DS4_VLLM_FLASHINFER_MLA_FORCE_TRTLLM_GEN",
        "DS4_VLLM_FLASHINFER_MLA_FORCE_CUTE_DSL",
        "DS4_VLLM_READY_RESPONSE_COMPAT",
        "DS4_VLLM_FLASHMLA_SPARSE_TRITON_BF16_FALLBACK",
        "DS4_VLLM_ENABLE_TRIM_MEMORY",
        "DS4_VLLM_INDEX_TOPK_OVERRIDE",
        "VLLM_TRITON_MLA_SPARSE",
        "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT",
        "VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR",
        "VLLM_DS4_PP_TCP_TENSOR_DICT",
    ):
        value = os.getenv(name, "")
        if value.strip().lower() not in {"", "0", "false", "no", "off"}:
            return True
    return False


def _strict() -> bool:
    value = os.getenv("DS4_VLLM_RUNTIME_PATCHES_STRICT", "")
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _resolve_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw))).resolve()


def _looks_like_vllm_source_root(path_text: str) -> bool:
    candidate = path_text.strip()
    if candidate == "":
        return False
    try:
        init_file = _resolve_path(candidate).joinpath("vllm", "__init__.py")
    except OSError:
        return False
    return init_file.exists() and init_file.is_file()


def _enforce_source_root() -> None:
    source_root_text = os.getenv("DS4_VLLM_SOURCE_ROOT", "")
    if source_root_text.strip() == "":
        return
    source_root = _resolve_path(source_root_text)
    if not (source_root / "vllm" / "__init__.py").is_file():
        raise RuntimeError(
            f"DS4 source-root guard: not a vLLM source root: {source_root}"
        )
    sanitized = [str(source_root)]
    seen = {str(source_root)}
    for entry in sys.path:
        if entry == "":
            continue
        try:
            resolved = _resolve_path(entry)
        except OSError:
            continue
        resolved_text = str(resolved)
        if resolved == source_root:
            continue
        if _looks_like_vllm_source_root(resolved_text):
            continue
        if resolved_text in seen:
            continue
        sanitized.append(resolved_text)
        seen.add(resolved_text)
    sys.path[:] = sanitized


if _enabled():
    try:
        _enforce_source_root()
        from ds4_vllm_runtime.patches import apply_runtime_patches, write_import_proof

        write_import_proof("sitecustomize")
        apply_runtime_patches()
    except Exception as exc:
        print(f"DS4 vLLM runtime patch failed: {exc}", file=sys.stderr)
        if _strict():
            raise
