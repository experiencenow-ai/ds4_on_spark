import unittest

from scripts import verify_antirez_ds4_cuda_stack_stage_preload_patch as verify


class AntirezDs4CudaStackStagePreloadPatchTest(unittest.TestCase):
	def test_patch_has_expected_stage_preload_changes(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-cuda-stack-stage-range-preload.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text)
		self.assertEqual(errors, [])
