#!/usr/bin/env python3
"""Patch vLLM/DeepGEMM DS4 GB10 strict decode fast paths."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-vllm-gb10-strict-fastpaths"
DEEPGEMM_PATCH_ID = "ds4-deepgemm-sm121-family"


class PatchError(RuntimeError):
    pass


def _replace(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise PatchError(f"missing expected block: {label}")
    return text.replace(old, new, 1), True


def _insert_before(text: str, marker: str, block: str, label: str) -> tuple[str, bool]:
    if block in text:
        return text, False
    idx = text.find(marker)
    if idx < 0:
        raise PatchError(f"missing insertion marker: {label}")
    return text[:idx] + block + text[idx:], True


def _write(path: Path, original: str, patched: str, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    changed = original != patched
    if changed and write:
        backup = path.with_name(path.name + backup_suffix)
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(patched, encoding="utf-8")
    diff = ""
    if changed:
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(True),
                patched.splitlines(True),
                fromfile=str(path),
                tofile=str(path),
            )
        )
    return {"path": str(path), "changed": changed, "diff": diff}


def locate_package_dir(runtime_root: Path | None, package_dir: Path | None) -> Path:
    if package_dir is not None:
        if not package_dir.exists():
            raise PatchError(f"vLLM package dir not found: {package_dir}")
        return package_dir
    if runtime_root is None:
        raise PatchError("either --runtime-root or --vllm-package-dir is required")
    matches = sorted(glob.glob(str(runtime_root / "lib" / "python*" / "site-packages" / "vllm")))
    if len(matches) != 1:
        raise PatchError(f"expected one vLLM package dir under {runtime_root}, found {matches}")
    return Path(matches[0])


def patch_sparse_attn_indexer(text: str) -> str:
    if "rocm_aiter_sparse_attn_indexer_native" in text and "major >= 12" in text:
        return text
    old = """        return torch.ops.vllm.sparse_attn_indexer(
            hidden_states,
            _encode_layer_name(self.k_cache.prefix),
            self.k_cache.kv_cache,
            q_values,
            q_scale,
            k,
            weights,
            self.quant_block_size,
            self.scale_fmt,
            self.topk_tokens,
            self.head_dim,
            self.max_model_len,
            self.max_total_seq_len,
            self.topk_indices_buffer,
            self.skip_k_cache_insert,
            self.use_fp4_cache,
        )
"""
    new = """        if current_platform.is_cuda() and q_scale is None and not self.use_fp4_cache:
            major, _minor = torch.cuda.get_device_capability()
            if major >= 12:
                from vllm.v1.attention.ops.rocm_aiter_mla_sparse import (
                    rocm_aiter_sparse_attn_indexer_native,
                )
                return rocm_aiter_sparse_attn_indexer_native(
                    hidden_states,
                    _encode_layer_name(self.k_cache.prefix),
                    self.k_cache.kv_cache,
                    q_values,
                    k,
                    weights,
                    self.quant_block_size,
                    self.scale_fmt,
                    self.topk_tokens,
                    self.head_dim,
                    self.max_model_len,
                    self.max_total_seq_len,
                    self.topk_indices_buffer,
                    skip_k_cache_insert=self.skip_k_cache_insert,
                )
        return torch.ops.vllm.sparse_attn_indexer(
            hidden_states,
            _encode_layer_name(self.k_cache.prefix),
            self.k_cache.kv_cache,
            q_values,
            q_scale,
            k,
            weights,
            self.quant_block_size,
            self.scale_fmt,
            self.topk_tokens,
            self.head_dim,
            self.max_model_len,
            self.max_total_seq_len,
            self.topk_indices_buffer,
            self.skip_k_cache_insert,
            self.use_fp4_cache,
        )
"""
    text, _ = _replace(text, old, new, "SM12 sparse indexer direct fast path")
    return text


def patch_mla_indexer_backend(text: str) -> str:
    if "self.scheduler_metadata_buffer.zero_()" in text and "elif has_deep_gemm()" in text:
        return text
    new = """            if current_platform.is_cuda():
                self.scheduler_metadata_buffer.zero_()
            elif has_deep_gemm():
                self.scheduler_metadata_buffer[:] = get_paged_mqa_logits_metadata(
                    seq_lens,
                    self.kv_cache_spec.storage_block_size,
                    self.num_sms,
                )
"""
    old_fallback = """            if current_platform.is_cuda() and has_deep_gemm():
                try:
                    self.scheduler_metadata_buffer[:] = get_paged_mqa_logits_metadata(
                        seq_lens,
                        self.kv_cache_spec.storage_block_size,
                        self.num_sms,
                    )
                except RuntimeError as err:
                    if "Unsupported architecture" not in str(err):
                        raise
                    self.scheduler_metadata_buffer.zero_()
"""
    if old_fallback in text:
        text, _ = _replace(text, old_fallback, new, "SM12 metadata fallback removal")
        return text
    old = """            if current_platform.is_cuda() and has_deep_gemm():
                self.scheduler_metadata_buffer[:] = get_paged_mqa_logits_metadata(
                    seq_lens,
                    self.kv_cache_spec.storage_block_size,
                    self.num_sms,
                )
"""
    text, _ = _replace(text, old, new, "SM12 metadata bypass for direct Triton indexer")
    return text


TRITON_DECODE1_BLOCK = '''@triton.jit
def _fp8_paged_mqa_logits_decode1_kernel(
    q_ptr,
    kv_ptr,
    scale_ptr,
    weights_ptr,
    context_lens_ptr,
    block_tables_ptr,
    logits_ptr,
    max_model_len: tl.constexpr,
    block_table_stride: tl.constexpr,
    kv_block_stride: tl.constexpr,
    kv_token_stride: tl.constexpr,
    scale_block_stride: tl.constexpr,
    scale_token_stride: tl.constexpr,
    block_size: tl.constexpr,
    head_dim: tl.constexpr,
    num_heads: tl.constexpr,
    BLOCK_M: tl.constexpr,
    BLOCK_H: tl.constexpr,
    BLOCK_D: tl.constexpr,
):
    batch_id = tl.program_id(0)
    token_start = tl.program_id(1) * BLOCK_M
    token_offsets = token_start + tl.arange(0, BLOCK_M)
    context_len = tl.load(context_lens_ptr + batch_id)
    in_context = token_offsets < context_len
    in_range = token_offsets < max_model_len
    block_ranks = token_offsets // block_size
    block_offsets = token_offsets - (block_ranks * block_size)
    physical_blocks = tl.load(
        block_tables_ptr + batch_id * block_table_stride + block_ranks,
        mask=in_context,
        other=0,
    )
    acc = tl.zeros((BLOCK_M,), tl.float32)
    for head_start in range(0, num_heads, BLOCK_H):
        head_offsets = head_start + tl.arange(0, BLOCK_H)
        head_mask = head_offsets < num_heads
        dot_acc = tl.zeros((BLOCK_M, BLOCK_H), tl.float32)
        for dim_start in range(0, head_dim, BLOCK_D):
            dim_offsets = dim_start + tl.arange(0, BLOCK_D)
            dim_mask = dim_offsets < head_dim
            q_vals = tl.load(
                q_ptr
                + batch_id * num_heads * head_dim
                + head_offsets[:, None] * head_dim
                + dim_offsets[None, :],
                mask=head_mask[:, None] & dim_mask[None, :],
                other=0.0,
            )
            k_vals = tl.load(
                kv_ptr
                + physical_blocks[:, None] * kv_block_stride
                + block_offsets[:, None] * kv_token_stride
                + dim_offsets[None, :],
                mask=in_context[:, None] & dim_mask[None, :],
                other=0.0,
            )
            dot_acc += tl.dot(k_vals, tl.trans(q_vals), out_dtype=tl.float32)
        weights = tl.load(
            weights_ptr + batch_id * num_heads + head_offsets,
            mask=head_mask,
            other=0.0,
        )
        acc += tl.sum(tl.maximum(dot_acc, 0.0) * weights[None, :], axis=1)
    scales = tl.load(
        scale_ptr
        + physical_blocks * scale_block_stride
        + block_offsets * scale_token_stride,
        mask=in_context,
        other=0.0,
    )
    out = tl.where(in_context, acc * scales, -float("inf"))
    tl.store(logits_ptr + batch_id * max_model_len + token_offsets, out, mask=in_range)


def fp8_paged_mqa_logits_triton_decode1(
    q: torch.Tensor,
    kv_cache: torch.Tensor,
    weights: torch.Tensor,
    context_lens: torch.Tensor,
    block_tables: torch.Tensor,
    max_model_len: int,
) -> torch.Tensor:
    batch_size, next_n, heads, head_dim = q.shape
    assert next_n == 1
    if context_lens.dim() > 1:
        context_lens = context_lens.squeeze(-1)
    block_size = kv_cache.shape[1]
    kv_cache_flat = kv_cache.view(kv_cache.shape[0], -1)
    kv_values = kv_cache_flat[:, : block_size * head_dim]
    kv_values = kv_values.view(current_platform.fp8_dtype()).view(
        kv_cache.shape[0], block_size, head_dim
    )
    kv_scales = kv_cache_flat[:, block_size * head_dim :]
    kv_scales = kv_scales.view(torch.float32).view(kv_cache.shape[0], block_size)
    logits = torch.empty(
        [batch_size, max_model_len],
        device=q.device,
        dtype=torch.float32,
    )
    _fp8_paged_mqa_logits_decode1_kernel[
        (batch_size, triton.cdiv(max_model_len, 16))
    ](
        q,
        kv_values,
        kv_scales,
        weights,
        context_lens,
        block_tables,
        logits,
        max_model_len,
        block_tables.stride(0),
        kv_values.stride(0),
        kv_values.stride(1),
        kv_scales.stride(0),
        kv_scales.stride(1),
        block_size,
        head_dim,
        heads,
        BLOCK_M=16,
        BLOCK_H=16,
        BLOCK_D=64,
    )
    return logits


'''


def patch_rocm_aiter_mla_sparse(text: str) -> str:
    text, _ = _insert_before(
        text,
        "# Taken from https://github.com/deepseek-ai/DeepGEMM/blob/main/tests/test_attention.py#L156\n",
        TRITON_DECODE1_BLOCK,
        "decode1 Triton paged MQA logits",
    )
    old = """    if aiter_paged_mqa_logits_module is not None:
        if _ON_GFX942:
"""
    new = """    if current_platform.is_cuda() and next_n == 1:
        return fp8_paged_mqa_logits_triton_decode1(
            q_fp8,
            kv_cache_fp8,
            weights,
            context_lens,
            block_tables,
            max_model_len,
        )

    if aiter_paged_mqa_logits_module is not None:
        if _ON_GFX942:
"""
    text, _ = _replace(text, old, new, "SM12 decode1 Triton logits route")
    old = """    score = torch.einsum("mhd,nd->hmn", q, k).float() * scale
"""
    new = """    scale = scale.reshape(-1).view(1, 1, seq_len_kv)
    score = torch.einsum("mhd,nd->hmn", q, k).float() * scale
"""
    text, _ = _replace(text, old, new, "SM12 unpaged MQA scale broadcast")
    return text


def patch_deepseek_v4_model(text: str) -> str:
    text, _ = _replace(
        text,
        """        if torch.cuda.get_device_capability(device)[0] != 10:
            raise NotImplementedError("DeepGEMM MegaMoE requires SM100 GPUs.")
""",
        """        if torch.cuda.get_device_capability(device)[0] < 10:
            raise NotImplementedError("DeepGEMM MegaMoE requires SM100+ GPUs.")
""",
        "MegaMoE SM100+ runtime gate",
    )
    text = text.replace(
        "        import vllm.third_party.deep_gemm as deep_gemm\n",
        "        import deep_gemm\n",
    )
    return text


def patch_deepseek_v4_attention(text: str) -> str:
    old = "list(self._einsum_recipe),"
    new = "list((1, 1, 128) if wo_a_scale.dtype == torch.int32 else (1, 128, 128)),"
    text, _ = _replace(text, old, new, "DeepGEMM fp8_einsum recipe from scale layout")
    old = """    try:
        fp8_einsum(equation, (a, a_scale), (b, b_scale), out, recipe=tuple(recipe))
"""
    new = """    call_a_scale = _upcast_e8m0_to_fp32(a_scale).contiguous() if a_scale.dtype == torch.float8_e8m0fnu else a_scale
    call_b_scale = _upcast_e8m0_to_fp32(b_scale).contiguous() if b_scale.dtype == torch.float8_e8m0fnu else b_scale
    try:
        fp8_einsum(equation, (a, call_a_scale), (b, call_b_scale), out, recipe=tuple(recipe))
"""
    text, _ = _replace(text, old, new, "DeepGEMM fp8_einsum E8M0 scale normalization")
    if "DS4 GB10 fp8_einsum compatibility path" not in text:
        old = """    call_a_scale = _upcast_e8m0_to_fp32(a_scale).contiguous() if a_scale.dtype == torch.float8_e8m0fnu else a_scale
    call_b_scale = _upcast_e8m0_to_fp32(b_scale).contiguous() if b_scale.dtype == torch.float8_e8m0fnu else b_scale
"""
        new = """    if current_platform.is_cuda() and current_platform.is_device_capability_family(120):
        # DS4 GB10 fp8_einsum compatibility path: avoid SM100 tcgen05 DeepGEMM.
        if equation == "bhr,hdr->bhd":
            fallback_bhr_hdr()
            return
        raise RuntimeError(f"DS4 GB10 fp8_einsum requires a non-DeepGEMM implementation for {equation}")
    call_a_scale = _upcast_e8m0_to_fp32(a_scale).contiguous() if a_scale.dtype == torch.float8_e8m0fnu else a_scale
    call_b_scale = _upcast_e8m0_to_fp32(b_scale).contiguous() if b_scale.dtype == torch.float8_e8m0fnu else b_scale
"""
        text, _ = _replace(text, old, new, "GB10 fp8_einsum DeepGEMM bypass")
    return text


def patch_mxfp4_oracle(text: str) -> str:
    if "DS4 GB10: FlashInfer CUTLASS MXFP4+MXFP8 is the SM120-family fast path." not in text:
        old = """    if (
        current_platform.is_rocm()
        and config.routing_method == RoutingMethodType.DeepseekV4
    ):
        priority_backends = [
            Mxfp4MoeBackend.TRITON_UNFUSED,
            Mxfp4MoeBackend.AITER_MXFP4_BF16,
        ]
    else:
        priority_backends = _get_priority_backends()
"""
        new = """    if (
        current_platform.is_rocm()
        and config.routing_method == RoutingMethodType.DeepseekV4
    ):
        priority_backends = [
            Mxfp4MoeBackend.TRITON_UNFUSED,
            Mxfp4MoeBackend.AITER_MXFP4_BF16,
        ]
    elif current_platform.is_cuda() and current_platform.is_device_capability_family(120):
        # DS4 GB10: FlashInfer CUTLASS MXFP4+MXFP8 is the SM120-family fast path.
        priority_backends = [
            Mxfp4MoeBackend.FLASHINFER_CUTLASS_MXFP4_MXFP8,
        ]
    else:
        priority_backends = _get_priority_backends()
"""
        text, _ = _replace(text, old, new, "GB10 FlashInfer CUTLASS MXFP8 selector")
    if "DS4 FlashInfer CUTLASS converter: DeepSeek V4 stores gate/up contiguously." not in text:
        old = """    if mxfp4_backend in TRTLLM_BACKENDS:
        assert _cache_permute_indices is not None
"""
        new = """    if mxfp4_backend == Mxfp4MoeBackend.FLASHINFER_CUTLASS_MXFP4_MXFP8:
        from flashinfer import block_scale_interleave

        # DS4 FlashInfer CUTLASS converter: DeepSeek V4 stores gate/up contiguously.
        w13_weight = w13_weight.data
        w2_weight = w2_weight.data
        w13_weight_scale = w13_weight_scale.data
        w2_weight_scale = w2_weight_scale.data

        w1_weight = w13_weight[:, :intermediate_size, :]
        w3_weight = w13_weight[:, intermediate_size:, :]
        w13_weight = torch.cat([w3_weight, w1_weight], dim=1).contiguous()

        w1_scale = w13_weight_scale[:, :intermediate_size, :]
        w3_scale = w13_weight_scale[:, intermediate_size:, :]
        w13_weight_scale = torch.cat([w3_scale, w1_scale], dim=1).contiguous()

        if w13_bias is not None:
            w13_bias = w13_bias.data.to(torch.float32)
            b1 = w13_bias[:, :intermediate_size]
            b3 = w13_bias[:, intermediate_size:]
            w13_bias = torch.cat([b3, b1], dim=1).to(torch.bfloat16).contiguous()
        if w2_bias is not None:
            w2_bias = w2_bias.data

        w13_shape = w13_weight_scale.shape
        w13_weight_scale = block_scale_interleave(
            w13_weight_scale.view(torch.uint8)
        ).reshape(w13_shape)
        w2_shape = w2_weight_scale.shape
        w2_weight_scale = block_scale_interleave(
            w2_weight_scale.view(torch.uint8)
        ).reshape(w2_shape)

        return (
            w13_weight,
            w2_weight,
            w13_weight_scale,
            w2_weight_scale,
            w13_bias,
            w2_bias,
        )

    if mxfp4_backend in TRTLLM_BACKENDS:
        assert _cache_permute_indices is not None
"""
        text, _ = _replace(text, old, new, "GB10 FlashInfer CUTLASS DeepSeek V4 conversion")
    return text


def apply_vllm_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    targets = {
        "sparse_attn_indexer": (
            package_dir / "model_executor" / "layers" / "sparse_attn_indexer.py",
            patch_sparse_attn_indexer,
        ),
        "mla_indexer_backend": (
            package_dir / "v1" / "attention" / "backends" / "mla" / "indexer.py",
            patch_mla_indexer_backend,
        ),
        "rocm_aiter_mla_sparse": (
            package_dir / "v1" / "attention" / "ops" / "rocm_aiter_mla_sparse.py",
            patch_rocm_aiter_mla_sparse,
        ),
        "deepseek_v4_model": (
            package_dir / "model_executor" / "models" / "deepseek_v4.py",
            patch_deepseek_v4_model,
        ),
        "deepseek_v4_attention": (
            package_dir / "model_executor" / "layers" / "deepseek_v4_attention.py",
            patch_deepseek_v4_attention,
        ),
        "mxfp4_oracle": (
            package_dir / "model_executor" / "layers" / "fused_moe" / "oracle" / "mxfp4.py",
            patch_mxfp4_oracle,
        ),
    }
    files = {}
    for name, (path, patch_fn) in targets.items():
        if not path.exists():
            raise PatchError(f"missing target file: {path}")
        original = path.read_text(encoding="utf-8")
        patched = patch_fn(original)
        files[name] = _write(path, original, patched, backup_suffix=backup_suffix, write=write)
    return {
        "patch_id": PATCH_ID,
        "package_dir": str(package_dir),
        "write": write,
        "changed": any(item["changed"] for item in files.values()),
        "files": files,
    }


def patch_deepgemm_einsum_api(text: str) -> str:
    replacements = [
        (
            """    } else if (arch_major == 10) {
        sm100_bmn_bnk_mn_gemm(a, b, d, s, m, n, k);
""",
            """    } else if (arch_major >= 10) {
        sm100_bmn_bnk_mn_gemm(a, b, d, s, m, n, k);
""",
            "SM12 bmk,bnk einsum dispatch",
        ),
        (
            """    } else if (arch_major == 10) {
        sm100_bf16_bhr_hdr_bhd(A, B, D, b, h, r, d);
""",
            """    } else if (arch_major >= 10) {
        sm100_bf16_bhr_hdr_bhd(A, B, D, b, h, r, d);
""",
            "SM12 bhr,hdr BF16 dispatch",
        ),
        (
            """    } else if (arch_major == 10) {
        sm100_bf16_bhd_hdr_bhr(A, B, D, b, h, r, d);
""",
            """    } else if (arch_major >= 10) {
        sm100_bf16_bhd_hdr_bhr(A, B, D, b, h, r, d);
""",
            "SM12 bhd,hdr BF16 dispatch",
        ),
        (
            """    if (arch_major == 10) {
        sm100_fp8_bmm(a, transformed_sfa, b, transformed_sfb, c, d, batch_size, m, n, k, gran_k_a, gran_k_b, major_a, major_b, compiled_dims);
""",
            """    if (arch_major >= 10) {
        sm100_fp8_bmm(a, transformed_sfa, b, transformed_sfb, c, d, batch_size, m, n, k, gran_k_a, gran_k_b, major_a, major_b, compiled_dims);
""",
            "SM12 FP8 BMM dispatch",
        ),
        (
            'expr == "bhd,hdr->bhr" and arch_major == 10',
            'expr == "bhd,hdr->bhr" and arch_major >= 10',
            "SM12 bhd,hdr FP8 dispatch",
        ),
        (
            'expr == "bhd,bhr->hdr" and arch_major == 10',
            'expr == "bhd,bhr->hdr" and arch_major >= 10',
            "SM12 bhd,bhr FP8 dispatch",
        ),
    ]
    for old, new, label in replacements:
        text, _ = _replace(text, old, new, label)
    return text


def apply_deepgemm_source_patch(source_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    replacements = {
        "layout_api": (
            source_dir / "csrc" / "apis" / "layout.hpp",
            ("arch_major == 10", "arch_major >= 10", "SM12 layout transform guard"),
        ),
        "mega_api": (
            source_dir / "csrc" / "apis" / "mega.hpp",
            ("if (arch_major == 10) {", "if (arch_major >= 10) {", "SM12 MegaMoE dispatch"),
        ),
        "heuristics_runtime": (
            source_dir / "csrc" / "jit_kernels" / "heuristics" / "runtime.hpp",
            (
                "if (device_runtime->get_arch_major() != 10)",
                "if (device_runtime->get_arch_major() < 10)",
                "SM12 contiguous-layout alignment heuristic",
            ),
        ),
    }
    files = {}
    for name, (path, (old, new, label)) in replacements.items():
        if not path.exists():
            raise PatchError(f"missing target file: {path}")
        original = path.read_text(encoding="utf-8")
        patched, _ = _replace(original, old, new, label)
        files[name] = _write(path, original, patched, backup_suffix=backup_suffix, write=write)
    path = source_dir / "csrc" / "apis" / "einsum.hpp"
    if not path.exists():
        raise PatchError(f"missing target file: {path}")
    original = path.read_text(encoding="utf-8")
    patched = patch_deepgemm_einsum_api(original)
    files["einsum_api"] = _write(path, original, patched, backup_suffix=backup_suffix, write=write)
    return {
        "patch_id": DEEPGEMM_PATCH_ID,
        "source_dir": str(source_dir),
        "write": write,
        "changed": any(item["changed"] for item in files.values()),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root")
    parser.add_argument("--vllm-package-dir")
    parser.add_argument("--deepgemm-source-dir")
    parser.add_argument("--backup-suffix", default=".ds4_gb10_strict_fastpaths_bak")
    parser.add_argument("--check", action="store_true", help="Show whether changes are needed without writing.")
    args = parser.parse_args()
    results: list[dict[str, Any]] = []
    if args.runtime_root or args.vllm_package_dir:
        package_dir = locate_package_dir(
            Path(args.runtime_root).expanduser() if args.runtime_root else None,
            Path(args.vllm_package_dir).expanduser() if args.vllm_package_dir else None,
        )
        results.append(
            apply_vllm_patch(package_dir, backup_suffix=args.backup_suffix, write=not args.check)
        )
    if args.deepgemm_source_dir:
        results.append(
            apply_deepgemm_source_patch(
                Path(args.deepgemm_source_dir).expanduser(),
                backup_suffix=args.backup_suffix,
                write=not args.check,
            )
        )
    if not results:
        raise PatchError("provide --runtime-root/--vllm-package-dir or --deepgemm-source-dir")
    print(json.dumps({"results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
