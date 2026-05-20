import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_gb10_strict_fastpaths as patcher


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


MLA_INDEXER_BACKEND = '''class Builder:
    def build(self):
            if current_platform.is_cuda() and has_deep_gemm():
                self.scheduler_metadata_buffer[:] = get_paged_mqa_logits_metadata(
                    seq_lens,
                    self.kv_cache_spec.storage_block_size,
                    self.num_sms,
                )
'''


MLA_INDEXER_BACKEND_FALLBACK = '''class Builder:
    def build(self):
            if current_platform.is_cuda() and has_deep_gemm():
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
'''


ROCM_AITER_MLA_SPARSE = '''def fp8_paged_mqa_logits_torch():
    return None


# Taken from https://github.com/deepseek-ai/DeepGEMM/blob/main/tests/test_attention.py#L156
def fp8_paged_mqa_logits_torch_real():
    return None


def rocm_fp8_paged_mqa_logits():
    if aiter_paged_mqa_logits_module is not None:
        if _ON_GFX942:
            return None


def fp8_mqa_logits_torch(q, k, scale):
    seq_len_kv = k.shape[0]
    score = torch.einsum("mhd,nd->hmn", q, k).float() * scale
'''


DEEPSEEK_V4 = '''class DeepseekV4MegaMoEExperts:
    def _check_runtime_supported(self):
        if torch.cuda.get_device_capability(device)[0] != 10:
            raise NotImplementedError("DeepGEMM MegaMoE requires SM100 GPUs.")

    def finalize_weights(self):
        import vllm.third_party.deep_gemm as deep_gemm
        deep_gemm.transform_sf_into_required_layout()

    def get_symm_buffer(self):
        import vllm.third_party.deep_gemm as deep_gemm
        return deep_gemm.get_symm_buffer_for_mega_moe()
'''


DEEPSEEK_V4_ATTENTION = '''def deepseek_v4_fp8_einsum(a, a_scale, b, b_scale, out):
    equation = "ab,bc->ac"
    try:
        fp8_einsum(equation, (a, a_scale), (b, b_scale), out, recipe=tuple(recipe))
    except RuntimeError:
        torch._scaled_mm()


def attention_forward(wo_a_scale):
    torch.ops.vllm.deepseek_v4_fp8_einsum(
        o_fp8,
        o_scale,
        wo_a_fp8,
        wo_a_scale,
        z,
        "bhr,hdr->bhd",
        list(self._einsum_recipe),
    )
'''


MXFP4_ORACLE = '''def select_deepseek_v4_mxfp4_moe_backend(config):
    if (
        current_platform.is_rocm()
        and config.routing_method == RoutingMethodType.DeepseekV4
    ):
        priority_backends = [
            Mxfp4MoeBackend.TRITON_UNFUSED,
            Mxfp4MoeBackend.AITER_MXFP4_BF16,
        ]
    else:
        priority_backends = _get_priority_backends()
    return priority_backends


def convert_weight_to_mxfp4_moe_kernel_format(mxfp4_backend):
    if mxfp4_backend in TRTLLM_BACKENDS:
        assert _cache_permute_indices is not None
        return None
'''


LAYOUT_HPP = '''if (sf.scalar_type() == torch::kFloat and (gran_k == 32 or gran_k == 128) and arch_major == 10) {
    return get_mn_major_tma_aligned_packed_ue8m0_tensor(broadcasted);
}
'''


MEGA_HPP = '''    if (arch_major == 10) {
        sm100_fp8_fp4_mega_moe(y);
    } else {
        DG_HOST_UNREACHABLE("Unsupported architecture");
    }
'''


RUNTIME_HPP = '''    static int get_theoretical_mk_alignment_for_contiguous_layout(const std::optional<int>& expected_m) {
        if (device_runtime->get_arch_major() != 10)
            return kLegacyMKAlignmentForContiguousLayout;
        return 240;
    }
'''


EINSUM_HPP = '''static void bmk_bnk_mn() {
    if (arch_major == 9) {
        sm90_bmn_bnk_mn_gemm(a, b, d, s, m, n, k);
    } else if (arch_major == 10) {
        sm100_bmn_bnk_mn_gemm(a, b, d, s, m, n, k);
    }
}
static void bhr_hdr_bhd() {
    if (use_cublaslt) {
        cublaslt_bhr_hdr_bhd(A, B, D, b, h, r, d);
    } else if (arch_major == 9) {
        sm90_bf16_bhr_hdr_bhd(A, B, D, b, h, r, d);
    } else if (arch_major == 10) {
        sm100_bf16_bhr_hdr_bhd(A, B, D, b, h, r, d);
    }
}
static void bhd_hdr_bhr() {
    if (use_cublaslt) {
        cublaslt_bhd_hdr_bhr(A, B, D, b, h, r, d);
    } else if (arch_major == 9) {
        sm90_bf16_bhd_hdr_bhr(A, B, D, b, h, r, d);
    } else if (arch_major == 10) {
        sm100_bf16_bhd_hdr_bhr(A, B, D, b, h, r, d);
    }
}
static void fp8_bmm() {
    if (arch_major == 10) {
        sm100_fp8_bmm(a, transformed_sfa, b, transformed_sfb, c, d, batch_size, m, n, k, gran_k_a, gran_k_b, major_a, major_b, compiled_dims);
    } else {
        sm90_fp8_bmm(a, transformed_sfa, b, transformed_sfb, c, d, batch_size, m, n, k, major_a, major_b, major_sfb, compiled_dims);
    }
}
static void fp8_einsum() {
    if (expr == "bhr,hdr->bhd") {
        fp8_bmm();
    } else if (expr == "bhd,hdr->bhr" and arch_major == 10) {
        fp8_bmm();
    } else if (expr == "bhd,bhr->hdr" and arch_major == 10) {
        fp8_bmm();
    }
}
'''


class PatchVllmDs4Gb10StrictFastpathsTest(unittest.TestCase):
    def test_sparse_indexer_patch_is_direct_and_idempotent(self) -> None:
        once = patcher.patch_sparse_attn_indexer(SPARSE_INDEXER)
        twice = patcher.patch_sparse_attn_indexer(once)
        self.assertEqual(once, twice)
        self.assertIn("major >= 12", once)
        self.assertIn("rocm_aiter_sparse_attn_indexer_native", once)
        self.assertNotIn("except RuntimeError", once)

    def test_mla_metadata_patch_does_not_call_unsupported_cuda_metadata(self) -> None:
        once = patcher.patch_mla_indexer_backend(MLA_INDEXER_BACKEND)
        twice = patcher.patch_mla_indexer_backend(once)
        self.assertEqual(once, twice)
        self.assertIn("self.scheduler_metadata_buffer.zero_()", once)
        self.assertIn("elif has_deep_gemm()", once)

    def test_mla_metadata_patch_removes_unsupported_arch_fallback(self) -> None:
        once = patcher.patch_mla_indexer_backend(MLA_INDEXER_BACKEND_FALLBACK)
        self.assertIn("self.scheduler_metadata_buffer.zero_()", once)
        self.assertIn("elif has_deep_gemm()", once)
        self.assertNotIn("Unsupported architecture", once)

    def test_triton_decode1_patch_is_idempotent(self) -> None:
        once = patcher.patch_rocm_aiter_mla_sparse(ROCM_AITER_MLA_SPARSE)
        twice = patcher.patch_rocm_aiter_mla_sparse(once)
        self.assertEqual(once, twice)
        self.assertIn("_fp8_paged_mqa_logits_decode1_kernel", once)
        self.assertIn("fp8_paged_mqa_logits_triton_decode1", once)
        self.assertIn("current_platform.is_cuda() and next_n == 1", once)
        self.assertIn("scale.reshape(-1).view(1, 1, seq_len_kv)", once)

    def test_deepseek_v4_model_uses_external_deepgemm_sm100_plus(self) -> None:
        patched = patcher.patch_deepseek_v4_model(DEEPSEEK_V4)
        self.assertIn("SM100+ GPUs", patched)
        self.assertIn("import deep_gemm", patched)
        self.assertNotIn("vllm.third_party.deep_gemm", patched)

    def test_deepseek_v4_attention_normalizes_e8m0_scales_for_deepgemm(self) -> None:
        once = patcher.patch_deepseek_v4_attention(DEEPSEEK_V4_ATTENTION)
        twice = patcher.patch_deepseek_v4_attention(once)
        self.assertEqual(once, twice)
        self.assertIn("_upcast_e8m0_to_fp32(a_scale)", once)
        self.assertIn("_upcast_e8m0_to_fp32(b_scale)", once)
        self.assertIn("(a, call_a_scale)", once)
        self.assertIn("(b, call_b_scale)", once)
        self.assertIn("wo_a_scale.dtype == torch.int32", once)
        self.assertIn("else (1, 128, 128)", once)
        self.assertIn("is_device_capability_family(120)", once)
        self.assertIn("DS4 GB10 fp8_einsum compatibility path", once)
        self.assertIn("fallback_bhr_hdr()", once)

    def test_mxfp4_oracle_prefers_flashinfer_cutlass_on_gb10_without_fallback(self) -> None:
        once = patcher.patch_mxfp4_oracle(MXFP4_ORACLE)
        twice = patcher.patch_mxfp4_oracle(once)
        self.assertEqual(once, twice)
        self.assertIn("is_device_capability_family(120)", once)
        self.assertIn("FLASHINFER_CUTLASS_MXFP4_MXFP8", once)
        self.assertIn("SM120-family fast path", once)
        self.assertIn("DS4 FlashInfer CUTLASS converter", once)
        self.assertIn("block_scale_interleave", once)
        self.assertIn("torch.cat([w3_weight, w1_weight]", once)
        gb10_block = once.split("is_device_capability_family(120):", 1)[1].split("else:", 1)[0]
        self.assertNotIn("MARLIN", gb10_block)
        self.assertNotIn("DEEPGEMM", gb10_block)

    def test_deepgemm_source_patch_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "csrc" / "apis").mkdir(parents=True)
            (root / "csrc" / "jit_kernels" / "heuristics").mkdir(parents=True)
            (root / "csrc" / "apis" / "layout.hpp").write_text(LAYOUT_HPP, encoding="utf-8")
            (root / "csrc" / "apis" / "mega.hpp").write_text(MEGA_HPP, encoding="utf-8")
            (root / "csrc" / "jit_kernels" / "heuristics" / "runtime.hpp").write_text(
                RUNTIME_HPP,
                encoding="utf-8",
            )
            (root / "csrc" / "apis" / "einsum.hpp").write_text(EINSUM_HPP, encoding="utf-8")
            once = patcher.apply_deepgemm_source_patch(root, backup_suffix=".bak", write=True)
            twice = patcher.apply_deepgemm_source_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(once["changed"])
            self.assertFalse(twice["changed"])
            self.assertIn("arch_major >= 10", (root / "csrc" / "apis" / "layout.hpp").read_text())
            self.assertIn("sm100_fp8_bmm", (root / "csrc" / "apis" / "einsum.hpp").read_text())
            self.assertNotIn("arch_major == 10", (root / "csrc" / "apis" / "einsum.hpp").read_text())
            self.assertIn("device_runtime->get_arch_major() < 10", (root / "csrc" / "jit_kernels" / "heuristics" / "runtime.hpp").read_text())

    def test_apply_vllm_patch_writes_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vllm"
            (root / "model_executor" / "layers").mkdir(parents=True)
            (root / "model_executor" / "models").mkdir(parents=True)
            (root / "model_executor" / "layers" / "fused_moe" / "oracle").mkdir(parents=True)
            (root / "v1" / "attention" / "backends" / "mla").mkdir(parents=True)
            (root / "v1" / "attention" / "ops").mkdir(parents=True)
            (root / "model_executor" / "layers" / "sparse_attn_indexer.py").write_text(
                SPARSE_INDEXER,
                encoding="utf-8",
            )
            (root / "v1" / "attention" / "backends" / "mla" / "indexer.py").write_text(
                MLA_INDEXER_BACKEND,
                encoding="utf-8",
            )
            (root / "v1" / "attention" / "ops" / "rocm_aiter_mla_sparse.py").write_text(
                ROCM_AITER_MLA_SPARSE,
                encoding="utf-8",
            )
            (root / "model_executor" / "models" / "deepseek_v4.py").write_text(
                DEEPSEEK_V4,
                encoding="utf-8",
            )
            (root / "model_executor" / "layers" / "deepseek_v4_attention.py").write_text(
                DEEPSEEK_V4_ATTENTION,
                encoding="utf-8",
            )
            (root / "model_executor" / "layers" / "fused_moe" / "oracle" / "mxfp4.py").write_text(
                MXFP4_ORACLE,
                encoding="utf-8",
            )
            result = patcher.apply_vllm_patch(root, backup_suffix=".bak", write=True)
            result2 = patcher.apply_vllm_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertFalse(result2["changed"])
            self.assertTrue(
                (root / "v1" / "attention" / "ops" / "rocm_aiter_mla_sparse.py.bak").exists()
            )


if __name__ == "__main__":
    unittest.main()
