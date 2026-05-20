import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_sm121_cutlass_scalar44_fallback as patcher


CUSTOM_OPS = '''import torch
from vllm.platforms import current_platform


def cutlass_scaled_mm(
    a: torch.Tensor,
    b: torch.Tensor,
    scale_a: torch.Tensor,
    scale_b: torch.Tensor,
    out_dtype: torch.dtype,
    bias: torch.Tensor | None = None,
) -> torch.Tensor:
    target_shape = (*a.shape[:-1], b.shape[1])
    a = a.view(-1, a.shape[-1])

    cutlass_compatible_b = b.shape[0] % 16 == 0 and b.shape[1] % 16 == 0
    if current_platform.is_rocm() or not cutlass_compatible_b:
        from vllm.model_executor.layers.quantization.compressed_tensors.triton_scaled_mm import (
            triton_scaled_mm,
        )

        out = triton_scaled_mm(a, b, scale_a, scale_b, out_dtype, bias)
    else:
        out = torch.empty((a.shape[0], b.shape[1]), dtype=out_dtype, device=a.device)
        torch.ops._C.cutlass_scaled_mm(out, a, b, scale_a, scale_b, bias)

    return out.view(*target_shape)
'''


class PatchVllmDs4Sm121CutlassScalar44FallbackTest(unittest.TestCase):
    def test_patch_custom_ops_is_idempotent(self) -> None:
        once = patcher.patch_custom_ops(CUSTOM_OPS)
        twice = patcher.patch_custom_ops(once)
        self.assertEqual(once, twice)
        self.assertIn("_ds4_should_fallback_cutlass_scaled_mm", once)
        self.assertIn("Not yet supported ScalarType 44", once)
        self.assertIn("_ds4_cutlass_scaled_mm_torch_fallback", once)
        self.assertIn("except RuntimeError as exc", once)

    def test_patch_package_dir_writes_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vllm"
            root.mkdir()
            custom_ops = root / "_custom_ops.py"
            custom_ops.write_text(CUSTOM_OPS, encoding="utf-8")
            result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertTrue((custom_ops.with_name(custom_ops.name + ".bak")).exists())
            result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertFalse(result2["changed"])


if __name__ == "__main__":
    unittest.main()
