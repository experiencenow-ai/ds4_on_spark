"""Runtime patches used by DS4 vLLM launcher wrappers."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from ds4_vllm_runtime.pp_tcp_transport_patch import patch_ds4_pp_tcp_tensor_transport
from ds4_vllm_runtime.vllm_env_registry import register_ds4_vllm_envs

_TRITON_SPARSE_BF16_KERNELS: tuple[Any, Any, Any] | None = None


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def _is_sm12_cuda_tensor(tensor: Any) -> bool:
    try:
        import torch
    except ImportError:
        return False
    if not getattr(tensor, "is_cuda", False):
        return False
    capability = torch.cuda.get_device_capability(tensor.device)
    return int(capability[0]) == 12


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


def allow_flashmla_sparse_torch_fallback() -> str:
    flashmla_sparse = importlib.import_module(
        "vllm.v1.attention.backends.mla.flashmla_sparse"
    )
    impl_cls = getattr(flashmla_sparse, "FlashMLASparseImpl")
    original = getattr(impl_cls, "_bf16_flash_mla_kernel")
    if getattr(original, "_ds4_sm12_torch_sparse_fallback", False):
        return "flashmla_sparse_torch_fallback"

    def _chunk_size() -> int:
        raw = os.getenv("DS4_VLLM_FLASHMLA_SPARSE_TORCH_FALLBACK_TOKENS", "8")
        try:
            return max(1, int(raw))
        except ValueError:
            return 8

    def _torch_sparse_mla(self, q, kv_c_and_k_pe_cache, topk_indices):  # type: ignore[no-untyped-def]
        import torch

        kv_flat = kv_c_and_k_pe_cache.reshape(-1, kv_c_and_k_pe_cache.shape[-1])
        num_tokens = int(q.shape[0])
        topk = int(topk_indices.shape[1])
        value_dim = int(self.kv_lora_rank)
        output = q.new_empty((num_tokens, int(self.num_heads), value_dim))
        chunk = _chunk_size()
        for start in range(0, num_tokens, chunk):
            end = min(start + chunk, num_tokens)
            q_chunk = q[start:end]
            indices = topk_indices[start:end].to(device=q.device)
            valid = indices >= 0
            max_valid = int(valid.sum(dim=1).max().item())
            if max_valid <= 0:
                output[start:end].zero_()
                continue
            indices = indices[:, :max_valid]
            valid = valid[:, :max_valid]
            topk = max_valid
            safe_indices = torch.where(valid, indices, torch.zeros_like(indices)).to(
                torch.long
            )
            gathered = kv_flat.index_select(0, safe_indices.reshape(-1)).reshape(
                end - start, topk, kv_flat.shape[-1]
            )
            scores = torch.einsum("thd,tkd->thk", q_chunk, gathered)
            scores = (scores * float(self.softmax_scale)).float()
            scores = scores.masked_fill(~valid[:, None, :], -1.0e30)
            probs = torch.softmax(scores, dim=-1)
            probs = torch.where(valid[:, None, :], probs, torch.zeros_like(probs))
            values = gathered[:, :, :value_dim]
            output[start:end] = torch.einsum(
                "thk,tkv->thv", probs.to(values.dtype), values
            )
        return output

    def bf16_kernel_with_torch_fallback(  # type: ignore[no-untyped-def]
        self, q, kv_c_and_k_pe_cache, topk_indices
    ):
        if _is_sm12_cuda_tensor(q):
            logger = getattr(flashmla_sparse, "logger", None)
            if logger is not None:
                logger.warning_once(
                    "DS4 SM12 FlashMLA sparse fallback: using chunked torch "
                    "top-k attention because flash_mla_sparse_fwd rejects SM12."
                )
            return _torch_sparse_mla(self, q, kv_c_and_k_pe_cache, topk_indices)
        return original(self, q, kv_c_and_k_pe_cache, topk_indices)

    bf16_kernel_with_torch_fallback._ds4_sm12_torch_sparse_fallback = True  # type: ignore[attr-defined]
    impl_cls._bf16_flash_mla_kernel = bf16_kernel_with_torch_fallback
    return "flashmla_sparse_torch_fallback"


def _load_triton_sparse_bf16_kernels() -> tuple[Any, Any, Any]:
    global _TRITON_SPARSE_BF16_KERNELS
    if _TRITON_SPARSE_BF16_KERNELS is not None:
        return _TRITON_SPARSE_BF16_KERNELS
    import triton
    import triton.language as tl

    @triton.jit
    def _score_kernel(
        q_ptr,
        kv_ptr,
        indices_ptr,
        scores_ptr,
        stride_q_t: tl.constexpr,
        stride_q_h: tl.constexpr,
        stride_q_d: tl.constexpr,
        stride_kv_t,
        stride_kv_d: tl.constexpr,
        num_kv_rows,
        stride_indices_t: tl.constexpr,
        stride_indices_c: tl.constexpr,
        stride_scores_t: tl.constexpr,
        stride_scores_h: tl.constexpr,
        stride_scores_c: tl.constexpr,
        num_heads: tl.constexpr,
        head_dim: tl.constexpr,
        num_candidates: tl.constexpr,
        scale: tl.constexpr,
        HEAD_BLOCK: tl.constexpr,
        BLOCK_C: tl.constexpr,
        BLOCK_D: tl.constexpr,
    ):
        token_idx = tl.program_id(0)
        head_block_idx = tl.program_id(1)
        candidate_block_idx = tl.program_id(2)
        head_offsets = (head_block_idx * HEAD_BLOCK) + tl.arange(0, HEAD_BLOCK)
        candidate_offsets = (candidate_block_idx * BLOCK_C) + tl.arange(0, BLOCK_C)
        dim_offsets = tl.arange(0, BLOCK_D)
        head_mask = head_offsets < num_heads
        candidate_mask = candidate_offsets < num_candidates
        dim_mask = dim_offsets < head_dim
        q = tl.load(
            q_ptr
            + (token_idx * stride_q_t)
            + (head_offsets[:, None] * stride_q_h)
            + (dim_offsets[None, :] * stride_q_d),
            mask=head_mask[:, None] & dim_mask[None, :],
            other=0.0,
        ).to(tl.float32)
        kv_indices = tl.load(
            indices_ptr
            + (token_idx * stride_indices_t)
            + (candidate_offsets * stride_indices_c),
            mask=candidate_mask,
            other=-1,
        )
        is_valid = (
            candidate_mask
            & (kv_indices >= 0)
            & (kv_indices < num_kv_rows)
        )
        safe_indices = tl.where(is_valid, kv_indices, 0)
        kv = tl.load(
            kv_ptr
            + (safe_indices.to(tl.int64)[:, None] * stride_kv_t)
            + (dim_offsets[None, :] * stride_kv_d),
            mask=is_valid[:, None] & dim_mask[None, :],
            other=0.0,
        ).to(tl.float32)
        scores = tl.dot(
            q,
            tl.trans(kv),
            input_precision="tf32",
            out_dtype=tl.float32,
        ) * scale
        scores = tl.where(head_mask[:, None] & is_valid[None, :], scores, -float("inf"))
        tl.store(
            scores_ptr
            + (token_idx * stride_scores_t)
            + (head_offsets[:, None] * stride_scores_h)
            + (candidate_offsets[None, :] * stride_scores_c),
            scores,
            mask=head_mask[:, None] & candidate_mask[None, :],
        )

    @triton.jit
    def _finish_kernel(
        scores_ptr,
        kv_ptr,
        indices_ptr,
        output_ptr,
        stride_scores_t: tl.constexpr,
        stride_scores_h: tl.constexpr,
        stride_scores_c: tl.constexpr,
        stride_kv_t,
        stride_kv_d: tl.constexpr,
        num_kv_rows,
        stride_indices_t: tl.constexpr,
        stride_indices_c: tl.constexpr,
        stride_output_t: tl.constexpr,
        stride_output_h: tl.constexpr,
        stride_output_d: tl.constexpr,
        value_dim: tl.constexpr,
        num_candidates: tl.constexpr,
        BLOCK_K: tl.constexpr,
        BLOCK_D: tl.constexpr,
    ):
        token_idx = tl.program_id(0)
        head_idx = tl.program_id(1)
        dim_block_idx = tl.program_id(2)
        candidate_offsets = tl.arange(0, BLOCK_K)
        dim_offsets = (dim_block_idx * BLOCK_D) + tl.arange(0, BLOCK_D)
        dim_mask = dim_offsets < value_dim
        max_score = -float("inf")
        for candidate_start in range(0, num_candidates, BLOCK_K):
            candidates = candidate_start + candidate_offsets
            candidate_mask = candidates < num_candidates
            kv_indices = tl.load(
                indices_ptr
                + (token_idx * stride_indices_t)
                + (candidates * stride_indices_c),
                mask=candidate_mask,
                other=-1,
            )
            is_valid = (
                candidate_mask
                & (kv_indices >= 0)
                & (kv_indices < num_kv_rows)
            )
            scores = tl.load(
                scores_ptr
                + (token_idx * stride_scores_t)
                + (head_idx * stride_scores_h)
                + (candidates * stride_scores_c),
                mask=is_valid,
                other=-float("inf"),
            ).to(tl.float32)
            max_score = tl.maximum(max_score, tl.max(scores, axis=0))
        has_tokens = max_score > -float("inf")
        safe_max = tl.where(has_tokens, max_score, 0.0)
        denom = 0.0
        acc = tl.zeros((BLOCK_D,), tl.float32)
        for candidate_start in range(0, num_candidates, BLOCK_K):
            candidates = candidate_start + candidate_offsets
            candidate_mask = candidates < num_candidates
            kv_indices = tl.load(
                indices_ptr
                + (token_idx * stride_indices_t)
                + (candidates * stride_indices_c),
                mask=candidate_mask,
                other=-1,
            )
            is_valid = (
                candidate_mask
                & (kv_indices >= 0)
                & (kv_indices < num_kv_rows)
            )
            safe_indices = tl.where(is_valid, kv_indices, 0)
            scores = tl.load(
                scores_ptr
                + (token_idx * stride_scores_t)
                + (head_idx * stride_scores_h)
                + (candidates * stride_scores_c),
                mask=is_valid,
                other=-float("inf"),
            ).to(tl.float32)
            weights = tl.where(is_valid, tl.exp(scores - safe_max), 0.0)
            denom += tl.sum(weights, axis=0)
            kv = tl.load(
                kv_ptr
                + (safe_indices.to(tl.int64)[:, None] * stride_kv_t)
                + (dim_offsets[None, :] * stride_kv_d),
                mask=is_valid[:, None] & dim_mask[None, :],
                other=0.0,
            ).to(tl.float32)
            acc += tl.sum(kv * weights[:, None], axis=0)
        output_value = tl.where(denom > 0.0, acc / denom, 0.0)
        tl.store(
            output_ptr
            + (token_idx * stride_output_t)
            + (head_idx * stride_output_h)
            + (dim_offsets * stride_output_d),
            output_value,
            mask=dim_mask,
        )

    _TRITON_SPARSE_BF16_KERNELS = (triton, _score_kernel, _finish_kernel)
    return _TRITON_SPARSE_BF16_KERNELS


def _triton_sparse_mla_bf16(self: Any, q: Any, kv_cache: Any, topk_indices: Any) -> Any:
    import torch

    triton, score_kernel, finish_kernel = _load_triton_sparse_bf16_kernels()
    if topk_indices.dim() == 3:
        if int(topk_indices.shape[1]) != 1:
            raise ValueError("expected sparse topk indices second dim to be 1")
        topk_indices = topk_indices[:, 0, :]
    if topk_indices.dtype != torch.int32:
        topk_indices = topk_indices.to(torch.int32)
    indices = topk_indices.contiguous()
    kv_flat = kv_cache.reshape(-1, kv_cache.shape[-1]).contiguous()
    num_tokens = int(q.shape[0])
    active_heads = int(self.num_heads)
    head_dim = int(q.shape[-1])
    value_dim = int(self.kv_lora_rank)
    num_candidates = int(indices.shape[1])
    output = q.new_empty((num_tokens, active_heads, value_dim))
    score_buffer = torch.empty(
        (num_tokens, active_heads, num_candidates),
        dtype=torch.float32,
        device=q.device,
    )
    score_head_block = int(os.getenv("DS4_VLLM_TRITON_SPARSE_BF16_HEAD_BLOCK", "8"))
    score_candidate_block = int(
        os.getenv("DS4_VLLM_TRITON_SPARSE_BF16_CANDIDATE_BLOCK", "32")
    )
    score_block_d = min(1024, triton.next_power_of_2(head_dim))
    score_grid = (
        num_tokens,
        triton.cdiv(active_heads, score_head_block),
        triton.cdiv(num_candidates, score_candidate_block),
    )
    score_kernel[score_grid](
        q,
        kv_flat,
        indices,
        score_buffer,
        q.stride(0),
        q.stride(1),
        q.stride(2),
        kv_flat.stride(0),
        kv_flat.stride(1),
        kv_flat.shape[0],
        indices.stride(0),
        indices.stride(1),
        score_buffer.stride(0),
        score_buffer.stride(1),
        score_buffer.stride(2),
        active_heads,
        head_dim,
        num_candidates,
        float(self.softmax_scale),
        HEAD_BLOCK=score_head_block,
        BLOCK_C=score_candidate_block,
        BLOCK_D=score_block_d,
        num_warps=4,
    )
    finish_block_d = min(256, triton.next_power_of_2(value_dim))
    finish_grid = (num_tokens, active_heads, triton.cdiv(value_dim, finish_block_d))
    finish_kernel[finish_grid](
        score_buffer,
        kv_flat,
        indices,
        output,
        score_buffer.stride(0),
        score_buffer.stride(1),
        score_buffer.stride(2),
        kv_flat.stride(0),
        kv_flat.stride(1),
        kv_flat.shape[0],
        indices.stride(0),
        indices.stride(1),
        output.stride(0),
        output.stride(1),
        output.stride(2),
        value_dim,
        num_candidates,
        BLOCK_K=128,
        BLOCK_D=finish_block_d,
        num_warps=4,
    )
    return output


def allow_flashmla_sparse_triton_bf16_fallback() -> str:
    flashmla_sparse = importlib.import_module(
        "vllm.v1.attention.backends.mla.flashmla_sparse"
    )
    impl_cls = getattr(flashmla_sparse, "FlashMLASparseImpl")
    original = getattr(impl_cls, "_bf16_flash_mla_kernel")
    if getattr(original, "_ds4_sm12_triton_sparse_bf16_fallback", False):
        return "flashmla_sparse_triton_bf16_fallback"

    def bf16_kernel_with_triton_fallback(  # type: ignore[no-untyped-def]
        self, q, kv_c_and_k_pe_cache, topk_indices
    ):
        if _is_sm12_cuda_tensor(q):
            logger = getattr(flashmla_sparse, "logger", None)
            if logger is not None:
                logger.warning_once(
                    "DS4 SM12 FlashMLA sparse fallback: using Triton indexed "
                    "BF16 top-k attention because flash_mla_sparse_fwd rejects SM12."
                )
            return _triton_sparse_mla_bf16(
                self,
                q,
                kv_c_and_k_pe_cache,
                topk_indices,
            )
        return original(self, q, kv_c_and_k_pe_cache, topk_indices)

    bf16_kernel_with_triton_fallback._ds4_sm12_triton_sparse_bf16_fallback = True  # type: ignore[attr-defined]
    impl_cls._bf16_flash_mla_kernel = bf16_kernel_with_triton_fallback
    return "flashmla_sparse_triton_bf16_fallback"


def override_index_topk() -> str:
    raw = os.getenv("DS4_VLLM_INDEX_TOPK_OVERRIDE", "").strip()
    if raw == "":
        return "index_topk_override_unset"
    try:
        override = int(raw)
    except ValueError as exc:
        raise ValueError("DS4_VLLM_INDEX_TOPK_OVERRIDE must be an integer") from exc
    if override <= 0:
        raise ValueError("DS4_VLLM_INDEX_TOPK_OVERRIDE must be positive")

    patched = 0
    for module_name, class_name in (
        ("vllm.model_executor.models.deepseek_v2", "DeepseekV2Model"),
        ("vllm.model_executor.models.glm4_moe_lite", "Glm4MoeLiteModel"),
    ):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        model_cls = getattr(module, class_name, None)
        if model_cls is None:
            continue
        original = getattr(model_cls, "__init__")
        if getattr(original, "_ds4_index_topk_override", False):
            patched += 1
            continue

        def __init__(self, *args, _original=original, _module=module, **kwargs):  # type: ignore[no-untyped-def]
            vllm_config = kwargs.get("vllm_config")
            if vllm_config is None and len(args) > 0:
                vllm_config = args[0]
            model_config = getattr(vllm_config, "model_config", None)
            hf_config = getattr(model_config, "hf_config", None)
            if hf_config is not None and hasattr(hf_config, "index_topk"):
                current = int(getattr(hf_config, "index_topk"))
                if not hasattr(hf_config, "_ds4_original_index_topk"):
                    setattr(hf_config, "_ds4_original_index_topk", current)
                if current != override:
                    setattr(hf_config, "index_topk", override)
                    logger = getattr(_module, "logger", None)
                    if logger is not None:
                        warn = getattr(logger, "warning_once", logger.warning)
                        warn(
                            "DS4 overriding sparse index_topk from %s to %s.",
                            current,
                            override,
                        )
            return _original(self, *args, **kwargs)

        __init__._ds4_index_topk_override = True  # type: ignore[attr-defined]
        model_cls.__init__ = __init__
        patched += 1
    return f"index_topk_override_{override}_classes_{patched}"


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
        backend = kwargs.get("backend", "auto")
        if (
            backend != "trtllm-gen"
            and block_tables is not None
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


def force_flashinfer_mla_cute_dsl_decode() -> str:
    flashinfer_sparse = importlib.import_module(
        "vllm.v1.attention.backends.mla.flashinfer_mla_sparse"
    )
    original = getattr(flashinfer_sparse, "trtllm_batch_decode_with_kv_cache_mla")
    if getattr(original, "_ds4_force_cute_dsl", False):
        return "flashinfer_mla_force_cute_dsl"

    def decode_with_cute_dsl(*args, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs.get("backend", "auto") == "auto":
            kwargs["backend"] = "cute-dsl"
        return original(*args, **kwargs)

    decode_with_cute_dsl._ds4_force_cute_dsl = True  # type: ignore[attr-defined]
    flashinfer_sparse.trtllm_batch_decode_with_kv_cache_mla = decode_with_cute_dsl
    return "flashinfer_mla_force_cute_dsl"


def allow_triton_mla_sparse_validation() -> str:
    triton_mla = importlib.import_module(
        "vllm.v1.attention.backends.mla.triton_mla"
    )
    backend_cls = getattr(triton_mla, "TritonMLABackend")
    original = getattr(backend_cls, "validate_configuration")
    original_func = getattr(original, "__func__", original)
    if getattr(original_func, "_ds4_triton_mla_sparse_validation", False):
        return "triton_mla_sparse_validation"

    def validate_configuration(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
        reasons = list(original(*args, **kwargs))
        use_sparse = kwargs.get("use_sparse")
        if use_sparse is None and len(args) >= 7:
            use_sparse = args[6]
        if use_sparse is True:
            reasons = [reason for reason in reasons if reason != "sparse not supported"]
        return reasons

    validate_configuration._ds4_triton_mla_sparse_validation = True  # type: ignore[attr-defined]
    backend_cls.validate_configuration = classmethod(validate_configuration)
    return "triton_mla_sparse_validation"


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
    if any(name.startswith("VLLM_DS4_") for name in os.environ) or os.getenv(
        "VLLM_TRITON_MLA_SPARSE"
    ) is not None:
        patches.append(register_ds4_vllm_envs())
    if (
        env_flag("VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT")
        or env_flag("VLLM_DS4_PP_TCP_TENSOR_DICT")
        or env_flag("VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR")
    ):
        patches.append(patch_ds4_pp_tcp_tensor_transport())
    if env_flag("DS4_VLLM_READY_RESPONSE_COMPAT"):
        patches.append(allow_missing_ready_response_block_size())
    if env_flag("DS4_VLLM_SM12_FLASHINFER_MLA_SPARSE"):
        patches.append(allow_sm12_flashinfer_mla_sparse())
    if env_flag("DS4_VLLM_SM12_FLASHMLA_SPARSE"):
        patches.append(allow_sm12_flashmla_sparse())
    if env_flag("DS4_VLLM_FLASHMLA_SPARSE_TORCH_FALLBACK"):
        patches.append(allow_flashmla_sparse_torch_fallback())
    if env_flag("DS4_VLLM_FLASHMLA_SPARSE_TRITON_BF16_FALLBACK"):
        patches.append(allow_flashmla_sparse_triton_bf16_fallback())
    if os.getenv("DS4_VLLM_INDEX_TOPK_OVERRIDE", "").strip() != "":
        patches.append(override_index_topk())
    if env_flag("DS4_VLLM_SM12_SPARSE_INDEXER_DENSE_FALLBACK"):
        patches.append(allow_sm12_sparse_indexer_dense_fallback())
    if env_flag("DS4_VLLM_FLASHINFER_MLA_SHARED_BLOCK_TABLES_2D"):
        patches.append(allow_flashinfer_mla_shared_block_tables_2d())
    if env_flag("DS4_VLLM_FLASHINFER_MLA_FORCE_TRTLLM_GEN"):
        patches.append(force_flashinfer_mla_trtllm_gen_decode())
    if env_flag("DS4_VLLM_FLASHINFER_MLA_FORCE_CUTE_DSL"):
        patches.append(force_flashinfer_mla_cute_dsl_decode())
    if env_flag("VLLM_TRITON_MLA_SPARSE"):
        patches.append(allow_triton_mla_sparse_validation())
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
