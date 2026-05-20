import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_gb10_runtime_fallbacks as patcher


ATTENTION = '''from vllm.model_executor.layers.quantization.utils.fp8_utils import (
    _upcast_e8m0_to_fp32,
)


def deepseek_v4_fp8_einsum(
    a: torch.Tensor,
    a_scale: torch.Tensor,
    b: torch.Tensor,
    b_scale: torch.Tensor,
    out: torch.Tensor,
    equation: str,
    recipe: list[int],
) -> None:
    fp8_einsum(equation, (a, a_scale), (b, b_scale), out, recipe=tuple(recipe))


def deepseek_v4_fp8_einsum_fake(
    a: torch.Tensor,
    a_scale: torch.Tensor,
    b: torch.Tensor,
    b_scale: torch.Tensor,
    out: torch.Tensor,
    equation: str,
    recipe: list[int],
) -> None:
    return None


class Layer:
    def project(self):
        wo_a_fp8 = self.wo_a.weight
        wo_a_scale = self.wo_a.weight_scale_inv

        z = torch.empty(())
        torch.ops.vllm.deepseek_v4_fp8_einsum(
            o_fp8,
            o_scale,
            wo_a_fp8,
            wo_a_scale,
            z,
            "bhr,hdr->bhd",
            list(self._einsum_recipe),
        )

    def prefill(self):
                    output_chunk, _, _ = flash_mla_sparse_fwd(
                        q=q[query_start:query_end],
                        kv=kv.view(-1, 1, q.shape[-1]),
                        indices=combined_indices.unsqueeze(1),
                        sm_scale=self.scale,
                        attn_sink=self.attn_sink,
                        topk_length=combined_lens,
                        out=output[query_start:query_end],
                    )
'''


SPARSE_INDEXER = '''class SparseAttnIndexer:
    def forward_cuda(self, hidden_states, q_quant, k, weights):
        if isinstance(q_quant, tuple):
            q_values, q_scale = q_quant
        else:
            q_values, q_scale = q_quant, None
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
'''


class PatchVllmDs4Gb10RuntimeFallbacksTest(unittest.TestCase):
    def test_attention_patch_is_idempotent(self) -> None:
        once = patcher.patch_deepseek_v4_attention(ATTENTION)
        twice = patcher.patch_deepseek_v4_attention(once)
        self.assertEqual(once, twice)
        self.assertIn("w8a8_triton_block_scaled_mm", once)
        self.assertIn("Unknown SF transformation", once)
        self.assertIn("wo_a_fp8.dim() == 2", once)
        self.assertIn("rocm_sparse_attn_prefill", once)

    def test_sparse_indexer_patch_is_idempotent(self) -> None:
        once = patcher.patch_sparse_attn_indexer(SPARSE_INDEXER)
        twice = patcher.patch_sparse_attn_indexer(once)
        self.assertEqual(once, twice)
        self.assertIn("Unsupported architecture", once)
        self.assertIn("rocm_aiter_sparse_attn_indexer_native", once)
        self.assertIn("q_scale is not None or self.use_fp4_cache", once)

    def test_patch_package_dir_writes_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vllm"
            attention_dir = root / "model_executor" / "layers"
            attention_dir.mkdir(parents=True)
            (attention_dir / "deepseek_v4_attention.py").write_text(
                ATTENTION, encoding="utf-8"
            )
            (attention_dir / "sparse_attn_indexer.py").write_text(
                SPARSE_INDEXER, encoding="utf-8"
            )
            result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertTrue((attention_dir / "deepseek_v4_attention.py.bak").exists())
            self.assertTrue((attention_dir / "sparse_attn_indexer.py.bak").exists())
            result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertFalse(result2["changed"])


if __name__ == "__main__":
    unittest.main()
