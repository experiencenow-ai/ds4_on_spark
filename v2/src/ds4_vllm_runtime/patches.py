"""Runtime patches used by DS4 vLLM launcher wrappers."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
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


def allow_sm12_flashinfer_mla_sparse() -> str:
    flashinfer_sparse = importlib.import_module(
        "vllm.v1.attention.backends.mla.flashinfer_mla_sparse"
    )

    @classmethod
    def supports_compute_capability(cls, capability):  # type: ignore[no-untyped-def]
        return capability.major in (10, 12)

    flashinfer_sparse.FlashInferMLASparseBackend.supports_compute_capability = (
        supports_compute_capability
    )
    return "flashinfer_mla_sparse_sm12_compute_capability"


def allow_sm12_sparse_indexer_dense_fallback() -> str:
    sparse_indexer = importlib.import_module(
        "vllm.model_executor.layers.sparse_attn_indexer"
    )
    indexer_cls = getattr(sparse_indexer, "SparseAttnIndexer")
    original = getattr(indexer_cls, "forward_cuda")
    if getattr(original, "_ds4_sm12_dense_fallback", False):
        return "sparse_indexer_dense_topk_fallback"
    custom_ops = importlib.import_module("vllm._custom_ops")

    def _fill_last_window(out, starts, ends, topk):  # type: ignore[no-untyped-def]
        import torch

        row_count = int(starts.shape[0])
        if row_count == 0:
            return
        offsets = torch.arange(topk, dtype=torch.int32, device=out.device).view(1, -1)
        window_starts = torch.maximum(starts, (ends - topk))
        lengths = torch.clamp(ends - window_starts, min=0, max=topk).view(-1, 1)
        values = (window_starts.view(-1, 1) + offsets).to(torch.int32)
        out[:row_count, :topk].copy_(torch.where(offsets < lengths, values, -1))

    def forward_cuda(self, hidden_states, q_quant, k, weights):  # type: ignore[no-untyped-def]
        attn_metadata = sparse_indexer.get_forward_context().attn_metadata
        if not isinstance(attn_metadata, dict):
            return original(self, hidden_states, q_quant, k, weights)
        k_cache_prefix = sparse_indexer._resolve_layer_name(self.k_cache.prefix)
        attn_metadata_narrowed = attn_metadata[k_cache_prefix]
        slot_mapping = attn_metadata_narrowed.slot_mapping
        num_tokens = int(slot_mapping.shape[0])
        if k is not None:
            k = k[:num_tokens]
        if not self.skip_k_cache_insert:
            custom_ops.indexer_k_quant_and_cache(
                k,
                self.k_cache.kv_cache,
                slot_mapping,
                self.quant_block_size,
                self.scale_fmt,
            )
        topk_indices_buffer = self.topk_indices_buffer
        topk_indices_buffer[: hidden_states.shape[0]].fill_(-1)
        topk = int(self.topk_tokens)
        if attn_metadata_narrowed.num_prefills > 0:
            prefill = attn_metadata_narrowed.prefill
            assert prefill is not None
            for chunk in prefill.chunks:
                chunk_out = topk_indices_buffer[chunk.token_start : chunk.token_end]
                _fill_last_window(
                    chunk_out,
                    chunk.cu_seqlen_ks.to(
                        device=chunk_out.device, dtype=chunk_out.dtype
                    ),
                    chunk.cu_seqlen_ke.to(
                        device=chunk_out.device, dtype=chunk_out.dtype
                    ),
                    topk,
                )
        if attn_metadata_narrowed.num_decodes > 0:
            decode = attn_metadata_narrowed.decode
            assert decode is not None
            decode_lens = decode.decode_lens.to(
                device=topk_indices_buffer.device, dtype=topk_indices_buffer.dtype
            )
            starts = (decode_lens - topk).clamp(min=0)
            _fill_last_window(
                topk_indices_buffer[: attn_metadata_narrowed.num_decode_tokens],
                starts,
                decode_lens,
                topk,
            )
        return topk_indices_buffer

    forward_cuda._ds4_sm12_dense_fallback = True  # type: ignore[attr-defined]
    indexer_cls.forward_cuda = forward_cuda
    return "sparse_indexer_dense_topk_fallback"


def allow_flashinfer_mla_shared_block_tables_2d() -> str:
    flashinfer_sparse = importlib.import_module(
        "vllm.v1.attention.backends.mla.flashinfer_mla_sparse"
    )
    original = getattr(flashinfer_sparse, "trtllm_batch_decode_with_kv_cache_mla")
    if getattr(original, "_ds4_shared_block_tables_2d", False):
        return "flashinfer_mla_shared_block_tables_2d"

    def decode_with_2d_block_tables(*args, **kwargs):  # type: ignore[no-untyped-def]
        block_tables = kwargs.get("block_tables")
        if (
            block_tables is not None
            and getattr(block_tables, "ndim", None) == 3
            and int(block_tables.shape[1]) == 1
        ):
            kwargs["block_tables"] = block_tables.squeeze(1)
        return original(*args, **kwargs)

    decode_with_2d_block_tables._ds4_shared_block_tables_2d = True  # type: ignore[attr-defined]
    flashinfer_sparse.trtllm_batch_decode_with_kv_cache_mla = (
        decode_with_2d_block_tables
    )
    return "flashinfer_mla_shared_block_tables_2d"


def force_flashinfer_mla_trtllm_gen_decode() -> str:
    flashinfer_sparse = importlib.import_module(
        "vllm.v1.attention.backends.mla.flashinfer_mla_sparse"
    )
    original = getattr(flashinfer_sparse, "trtllm_batch_decode_with_kv_cache_mla")
    if getattr(original, "_ds4_force_trtllm_gen", False):
        return "flashinfer_mla_force_trtllm_gen"

    def decode_with_trtllm_gen(*args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("backend", "auto") == "auto":
            kwargs["backend"] = "trtllm-gen"
        return original(*args, **kwargs)

    decode_with_trtllm_gen._ds4_force_trtllm_gen = True  # type: ignore[attr-defined]
    flashinfer_sparse.trtllm_batch_decode_with_kv_cache_mla = decode_with_trtllm_gen
    return "flashinfer_mla_force_trtllm_gen"


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
    if env_flag("DS4_VLLM_SM12_FLASHINFER_MLA_SPARSE"):
        patches.append(allow_sm12_flashinfer_mla_sparse())
    if env_flag("DS4_VLLM_SM12_FLASHMLA_SPARSE"):
        patches.append(allow_sm12_flashmla_sparse())
    if env_flag("DS4_VLLM_SM12_SPARSE_INDEXER_DENSE_FALLBACK"):
        patches.append(allow_sm12_sparse_indexer_dense_fallback())
    if env_flag("DS4_VLLM_FLASHINFER_MLA_SHARED_BLOCK_TABLES_2D"):
        patches.append(allow_flashinfer_mla_shared_block_tables_2d())
    if env_flag("DS4_VLLM_FLASHINFER_MLA_FORCE_TRTLLM_GEN"):
        patches.append(force_flashinfer_mla_trtllm_gen_decode())
    return patches


def write_import_proof(role: str) -> str | None:
    proof_json = os.getenv("DS4_VLLM_IMPORT_PROOF_JSON", "")
    if proof_json.strip() == "":
        return None
    proof_path = Path(proof_json).expanduser()
    if not proof_path.is_absolute():
        proof_path = Path.cwd() / proof_path
    suffix = proof_path.suffix or ".json"
    if proof_path.name.endswith(suffix):
        stem = proof_path.name[: -len(suffix)]
    else:
        stem = proof_path.name
    child_path = proof_path.with_name(f"{stem}.{role}.pid{os.getpid()}{suffix}")
    proof: dict[str, Any] = {
        "argv": sys.argv,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "python": sys.executable,
        "role": role,
        "sys_path_first": sys.path[:12],
        "pythonpath": os.getenv("PYTHONPATH", ""),
    }
    try:
        vllm_module = importlib.import_module("vllm")
        proof["vllm_file"] = str(Path(str(vllm_module.__file__)).resolve())
        proof["vllm_root"] = str(Path(str(vllm_module.__file__)).resolve().parent.parent)
        proof["vllm_version"] = str(getattr(vllm_module, "__version__", "unknown"))
    except Exception as exc:  # pragma: no cover - defensive diagnostic path
        proof["vllm_import_error"] = repr(exc)
    child_path.parent.mkdir(parents=True, exist_ok=True)
    child_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
    return str(child_path)
