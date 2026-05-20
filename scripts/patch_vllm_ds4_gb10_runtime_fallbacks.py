#!/usr/bin/env python3
"""Patch vLLM DeepSeek-V4 GB10 runtime fallbacks for PP execution."""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import shutil
from pathlib import Path
from typing import Any


PATCH_ID = "ds4-vllm-gb10-runtime-fallbacks"


class PatchError(RuntimeError):
    pass


def _replace(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        return text, False
    if old not in text:
        raise PatchError(f"missing expected block: {label}")
    return text.replace(old, new, 1), True


def _replace_between(
    text: str,
    start: str,
    end: str,
    new: str,
    label: str,
) -> tuple[str, bool]:
    if new in text:
        return text, False
    start_idx = text.find(start)
    if start_idx < 0:
        raise PatchError(f"missing expected block start: {label}")
    end_idx = text.find(end, start_idx)
    if end_idx < 0:
        raise PatchError(f"missing expected block end: {label}")
    return text[:start_idx] + new + text[end_idx:], True


def _write(
    path: Path,
    original: str,
    patched: str,
    *,
    backup_suffix: str,
    write: bool,
) -> dict[str, Any]:
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


def patch_deepseek_v4_attention(text: str) -> str:
    text, _ = _replace(
        text,
        """from vllm.model_executor.layers.quantization.utils.fp8_utils import (
    _upcast_e8m0_to_fp32,
)
""",
        """from vllm.model_executor.layers.quantization.utils.fp8_utils import (
    _upcast_e8m0_to_fp32,
    w8a8_triton_block_scaled_mm,
)
""",
        "fp8 utils import",
    )
    einsum_impl = '''def deepseek_v4_fp8_einsum(
    a: torch.Tensor,
    a_scale: torch.Tensor,
    b: torch.Tensor,
    b_scale: torch.Tensor,
    out: torch.Tensor,
    equation: str,
    recipe: list[int],
) -> None:
    def unpack_ue8m0_packed(scale: torch.Tensor, unpacked_k: int) -> torch.Tensor:
        shape = scale.shape[:-1] + (unpacked_k // 4, 4)
        exp_bits = scale.contiguous().view(torch.uint8).view(shape).to(torch.int32)
        return (exp_bits << 23).view(torch.float32).reshape(scale.shape[:-1] + (unpacked_k,))

    def fallback_bhr_hdr() -> None:
        T, H, R = a.shape
        D = out.shape[-1]
        b_view = b.view(H, D, R) if b.dim() == 2 else b
        if a_scale.dtype == torch.int32:
            a_scale_fp32 = unpack_ue8m0_packed(a_scale, R // 128)
        elif a_scale.dtype == torch.float8_e8m0fnu:
            a_scale_fp32 = _upcast_e8m0_to_fp32(a_scale).contiguous()
        else:
            a_scale_fp32 = a_scale.contiguous()
        if b_scale.dtype == torch.float8_e8m0fnu:
            b_scale_fp32 = _upcast_e8m0_to_fp32(b_scale).contiguous()
        elif b_scale.dtype == torch.int32:
            b_scale_fp32 = unpack_ue8m0_packed(b_scale, R // 128)
        else:
            b_scale_fp32 = b_scale.contiguous()
        b_scale_fp32 = b_scale_fp32.reshape(H, D // 128, R // 128)
        for h in range(H):
            out[:, h, :].copy_(
                w8a8_triton_block_scaled_mm(
                    a[:, h, :].contiguous(),
                    b_view[h, :, :].contiguous(),
                    a_scale_fp32[:, h, :].contiguous(),
                    b_scale_fp32[h, :, :].contiguous(),
                    [128, 128],
                    output_dtype=out.dtype,
                )
            )

    try:
        fp8_einsum(equation, (a, a_scale), (b, b_scale), out, recipe=tuple(recipe))
    except RuntimeError as e:
        msg = str(e)
        if (
            equation == "bhr,hdr->bhd"
            and ("t.dim() == N" in msg or "Unknown SF transformation" in msg)
        ):
            fallback_bhr_hdr()
            return
        raise


'''
    text, _ = _replace_between(
        text,
        "def deepseek_v4_fp8_einsum(",
        "\ndef deepseek_v4_fp8_einsum_fake(",
        einsum_impl,
        "deepseek_v4_fp8_einsum",
    )
    wo_a_patch = """        wo_a_fp8 = self.wo_a.weight
        wo_a_scale = self.wo_a.weight_scale_inv
        if wo_a_fp8.dim() == 2:
            wo_a_fp8 = wo_a_fp8.view(
                self.n_local_groups, self.o_lora_rank, o_fp8.shape[-1]
            )
        if wo_a_scale.dim() == 2:
            wo_a_scale = wo_a_scale.view(
                self.n_local_groups,
                self.o_lora_rank // 128,
                o_fp8.shape[-1] // 128,
            )

"""
    text, _ = _replace(
        text,
        """        wo_a_fp8 = self.wo_a.weight
        wo_a_scale = self.wo_a.weight_scale_inv

""",
        wo_a_patch,
        "wo_a grouped view",
    )
    text, _ = _replace(
        text,
        """                    output_chunk, _, _ = flash_mla_sparse_fwd(
                        q=q[query_start:query_end],
                        kv=kv.view(-1, 1, q.shape[-1]),
                        indices=combined_indices.unsqueeze(1),
                        sm_scale=self.scale,
                        attn_sink=self.attn_sink,
                        topk_length=combined_lens,
                        out=output[query_start:query_end],
                    )
""",
        """                    try:
                        output_chunk, _, _ = flash_mla_sparse_fwd(
                            q=q[query_start:query_end],
                            kv=kv.view(-1, 1, q.shape[-1]),
                            indices=combined_indices.unsqueeze(1),
                            sm_scale=self.scale,
                            attn_sink=self.attn_sink,
                            topk_length=combined_lens,
                            out=output[query_start:query_end],
                        )
                    except RuntimeError as e:
                        if "Sparse Attention Forward Kernel is only supported" not in str(e):
                            raise
                        rocm_sparse_attn_prefill(
                            q=q[query_start:query_end],
                            kv=kv.view(-1, 1, q.shape[-1]),
                            indices=combined_indices.unsqueeze(1),
                            topk_length=combined_lens,
                            scale=self.scale,
                            head_dim=self.head_dim,
                            attn_sink=self.attn_sink,
                            output=output[query_start:query_end],
                        )
""",
        "FlashMLA sparse prefill GB10 fallback",
    )
    text, _ = _replace(
        text,
        """        # We treat queries in the same seq as different queries
        # and later we only attend by generated indices.
        # q arrives pre-padded to self.padded_heads by the outer wrapper.
        q = q.unsqueeze(1)
""",
        """        fallback_q = q
        fallback_kv_cache = kv_cache

        # We treat queries in the same seq as different queries
        # and later we only attend by generated indices.
        # q arrives pre-padded to self.padded_heads by the outer wrapper.
        q = q.unsqueeze(1)
""",
        "FlashMLA sparse decode fallback inputs",
    )
    text, _ = _replace(
        text,
        """        out, _ = flash_mla_with_kvcache(
            q=q,
            k_cache=swa_cache,
            block_table=None,
            head_dim_v=512,
            tile_scheduler_metadata=tile_metadata,
            cache_seqlens=None,
            is_fp8_kvcache=True,
            indices=swa_indices,
            topk_length=swa_lens,
            softmax_scale=self.scale,
            attn_sink=self.attn_sink,
            extra_k_cache=kv_cache if not swa_only else None,
            extra_indices_in_kvcache=topk_indices,
            extra_topk_length=topk_lens,
            out=output.unsqueeze(1),
        )
""",
        """        try:
            out, _ = flash_mla_with_kvcache(
                q=q,
                k_cache=swa_cache,
                block_table=None,
                head_dim_v=512,
                tile_scheduler_metadata=tile_metadata,
                cache_seqlens=None,
                is_fp8_kvcache=True,
                indices=swa_indices,
                topk_length=swa_lens,
                softmax_scale=self.scale,
                attn_sink=self.attn_sink,
                extra_k_cache=kv_cache if not swa_only else None,
                extra_indices_in_kvcache=topk_indices,
                extra_topk_length=topk_lens,
                out=output.unsqueeze(1),
            )
        except RuntimeError as e:
            if "Unsupported architecture for sparse decode fwd" not in str(e):
                raise
            rocm_forward_decode_fallback(
                q=fallback_q,
                kv_cache=fallback_kv_cache,
                swa_k_cache=self.swa_cache_layer.kv_cache,
                swa_only=swa_only,
                topk_indices=topk_indices,
                topk_lens=topk_lens,
                swa_indices=swa_indices,
                swa_lens=swa_lens,
                attn_sink=self.attn_sink,
                scale=self.scale,
                head_dim=self.head_dim,
                nope_head_dim=self.nope_head_dim,
                rope_head_dim=self.rope_head_dim,
                output=output,
            )
""",
        "FlashMLA sparse decode unsupported-architecture fallback",
    )
    return text


def patch_sparse_attn_indexer(text: str) -> str:
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
    new = """        try:
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
        except RuntimeError as err:
            if "Unsupported architecture" not in str(err):
                raise
            if q_scale is not None or self.use_fp4_cache:
                raise
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
"""
    text, _ = _replace(text, old, new, "sparse indexer unsupported-architecture fallback")
    return text


def patch_mla_indexer_backend(text: str) -> str:
    old = """            if current_platform.is_cuda() and has_deep_gemm():
                self.scheduler_metadata_buffer[:] = get_paged_mqa_logits_metadata(
                    seq_lens,
                    self.kv_cache_spec.storage_block_size,
                    self.num_sms,
                )
"""
    new = """            if current_platform.is_cuda() and has_deep_gemm():
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
    text, _ = _replace(text, old, new, "paged MQA metadata unsupported-architecture fallback")
    return text


def apply_patch(package_dir: Path, *, backup_suffix: str, write: bool) -> dict[str, Any]:
    attention_path = package_dir / "model_executor" / "layers" / "deepseek_v4_attention.py"
    sparse_indexer_path = package_dir / "model_executor" / "layers" / "sparse_attn_indexer.py"
    mla_indexer_path = package_dir / "v1" / "attention" / "backends" / "mla" / "indexer.py"
    for path in (attention_path, sparse_indexer_path, mla_indexer_path):
        if not path.exists():
            raise PatchError(f"missing target file: {path}")
    attention_original = attention_path.read_text(encoding="utf-8")
    attention_patched = patch_deepseek_v4_attention(attention_original)
    sparse_indexer_original = sparse_indexer_path.read_text(encoding="utf-8")
    sparse_indexer_patched = patch_sparse_attn_indexer(sparse_indexer_original)
    mla_indexer_original = mla_indexer_path.read_text(encoding="utf-8")
    mla_indexer_patched = patch_mla_indexer_backend(mla_indexer_original)
    files = {
        "deepseek_v4_attention": _write(
            attention_path,
            attention_original,
            attention_patched,
            backup_suffix=backup_suffix,
            write=write,
        ),
        "sparse_attn_indexer": _write(
            sparse_indexer_path,
            sparse_indexer_original,
            sparse_indexer_patched,
            backup_suffix=backup_suffix,
            write=write,
        ),
        "mla_indexer_backend": _write(
            mla_indexer_path,
            mla_indexer_original,
            mla_indexer_patched,
            backup_suffix=backup_suffix,
            write=write,
        ),
    }
    return {
        "patch_id": PATCH_ID,
        "package_dir": str(package_dir),
        "write": write,
        "changed": any(item["changed"] for item in files.values()),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root")
    parser.add_argument("--vllm-package-dir")
    parser.add_argument("--backup-suffix", default=".ds4_gb10_runtime_fallbacks_bak")
    parser.add_argument("--check", action="store_true", help="Show whether changes are needed without writing.")
    args = parser.parse_args()
    package_dir = locate_package_dir(
        Path(args.runtime_root).expanduser() if args.runtime_root else None,
        Path(args.vllm_package_dir).expanduser() if args.vllm_package_dir else None,
    )
    result = apply_patch(package_dir, backup_suffix=args.backup_suffix, write=not args.check)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
