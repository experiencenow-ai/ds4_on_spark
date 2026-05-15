import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_cuda_explicit_stage_preload_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-explicit-stage-preload.patch")


class AntirezDs4CudaExplicitStagePreloadPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		errors = verify.validate_patch_text(PATCH.read_text(encoding="utf-8"))
		self.assertEqual(errors, [])

	def test_missing_preload_api_fails(self) -> None:
		text = PATCH.read_text(encoding="utf-8").replace("ds4_gpu_preload_model_range", "ds4_gpu_cache_model_range")
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("ds4_gpu_preload_model_range" in e for e in errors))


if __name__ == "__main__":
	unittest.main()
