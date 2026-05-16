import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_cuda_b512_multistep_kv_loop_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-b512-multistep-kv-loop.patch")


class AntirezDs4CudaB512MultistepKvLoopPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		self.assertEqual(verify.validate_patch_text(PATCH.read_text(encoding="utf-8")), [])

	def test_rejects_missing_kv_update(self) -> None:
		self.assertTrue(any("kv_update_success" in e for e in verify.validate_patch_text("+per_step_decode_ms\n")))


if __name__ == "__main__":
	unittest.main()
