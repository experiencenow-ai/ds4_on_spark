import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_sm121_mhc_reference as patcher


MHC = """@cache
def compute_num_split(block_k: int, k: int | None, grid_size: int) -> int:
    return 1

def mhc_pre():
    if current_platform.is_rocm():
        torch_reference()
    deep_gemm_reference()

def mhc_post():
    if current_platform.is_rocm():
        torch_reference()
    tilelang_reference()

def mhc_fused_post_pre():
    if num_tokens <= fma_token_threshold:
        mhc_fused_tilelang(
            comb_res_mix_flat,
            residual_flat,
        )
    else:
        mhc_post_tilelang()

def _hc_head_fused_kernel():
    if current_platform.is_rocm():
        _hc_head_fused_reference()
        return
    hc_head_fuse_tilelang()
"""


class PatchVllmDs4Sm121MhcReferenceTest(unittest.TestCase):
    def test_patch_mhc_is_idempotent(self) -> None:
        once = patcher.patch_mhc(MHC)
        twice = patcher.patch_mhc(once)
        self.assertEqual(once, twice)
        self.assertIn("def _ds4_use_torch_mhc_reference()", once)
        self.assertEqual(once.count("if _ds4_use_torch_mhc_reference():"), 4)
        self.assertIn("residual_cur = mhc_post", once)
        self.assertIn("major >= 12", once)

    def test_patch_package_dir_writes_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vllm"
            target_dir = root / "model_executor" / "layers"
            target_dir.mkdir(parents=True)
            mhc = target_dir / "mhc.py"
            mhc.write_text(MHC, encoding="utf-8")
            result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertTrue((mhc.with_name(mhc.name + ".bak")).exists())
            result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertFalse(result2["changed"])


if __name__ == "__main__":
    unittest.main()
