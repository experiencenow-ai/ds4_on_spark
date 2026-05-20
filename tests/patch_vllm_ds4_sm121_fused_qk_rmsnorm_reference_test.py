import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_sm121_fused_qk_rmsnorm_reference as patcher


FUSED_QK_RMSNORM = '''import torch

from vllm.triton_utils import tl, triton


@triton.jit
def _fused_q_kv_rmsnorm_kernel():
    pass


def fused_q_kv_rmsnorm(
    qr: torch.Tensor,
    kv: torch.Tensor,
    q_weight: torch.Tensor,
    kv_weight: torch.Tensor,
    eps: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    assert qr.ndim == 2 and kv.ndim == 2
    assert qr.shape[0] == kv.shape[0], (
        f"token dim mismatch: qr={qr.shape}, kv={kv.shape}"
    )
    assert qr.stride(-1) == 1 and kv.stride(-1) == 1
    assert q_weight.is_contiguous() and kv_weight.is_contiguous()

    q_size = qr.shape[1]
    kv_size = kv.shape[1]
    num_tokens = qr.shape[0]
    qr_out = torch.empty_like(qr)
    kv_out = torch.empty_like(kv)
    if num_tokens == 0:
        return qr_out, kv_out

    block_size = triton.next_power_of_2(max(q_size, kv_size))
    _fused_q_kv_rmsnorm_kernel[(num_tokens, 2)](
        qr,
        qr_out,
        q_weight,
        qr.stride(0),
        qr_out.stride(0),
        kv,
        kv_out,
        kv_weight,
        kv.stride(0),
        kv_out.stride(0),
        eps,
        Q_SIZE=q_size,
        KV_SIZE=kv_size,
        BLOCK_SIZE=block_size,
    )
    return qr_out, kv_out
'''


class PatchVllmDs4Sm121FusedQkRmsnormReferenceTest(unittest.TestCase):
    def test_patch_fused_qk_rmsnorm_is_idempotent(self) -> None:
        once = patcher.patch_fused_qk_rmsnorm(FUSED_QK_RMSNORM)
        twice = patcher.patch_fused_qk_rmsnorm(once)
        self.assertEqual(once, twice)
        self.assertIn("_ds4_should_fallback_fused_qk_rmsnorm", once)
        self.assertIn("_ds4_should_use_fused_qk_rmsnorm_reference", once)
        self.assertIn("Python.h", once)
        self.assertIn("cuda_utils.c", once)
        self.assertIn("_ds4_fused_q_kv_rmsnorm_reference", once)
        self.assertIn("except Exception as exc", once)

    def test_patch_package_dir_writes_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "vllm"
            target_dir = root / "v1" / "attention" / "ops" / "deepseek_v4_ops"
            target_dir.mkdir(parents=True)
            target = target_dir / "fused_qk_rmsnorm.py"
            target.write_text(FUSED_QK_RMSNORM, encoding="utf-8")
            result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertTrue(result["changed"])
            self.assertTrue((target.with_name(target.name + ".bak")).exists())
            result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
            self.assertFalse(result2["changed"])

    def test_patch_upgrades_existing_runtime_error_fallback(self) -> None:
        old_patch = patcher.patch_fused_qk_rmsnorm(FUSED_QK_RMSNORM).replace(
            "except Exception as exc:",
            "except RuntimeError as exc:",
        ).replace(
            "exc: BaseException, ref: torch.Tensor",
            "exc: RuntimeError, ref: torch.Tensor",
        )
        upgraded = patcher.patch_fused_qk_rmsnorm(old_patch)
        self.assertEqual(upgraded.count("_ds4_should_fallback_fused_qk_rmsnorm"), 2)
        self.assertIn("exc: BaseException, ref: torch.Tensor", upgraded)
        self.assertIn("except Exception as exc", upgraded)
        self.assertNotIn("except RuntimeError as exc", upgraded)


if __name__ == "__main__":
    unittest.main()
