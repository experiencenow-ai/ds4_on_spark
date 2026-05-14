import unittest

from scripts import verify_antirez_ds4_cuda_moe_probe_patch as verify


class AntirezDs4CudaMoeProbePatchTest(unittest.TestCase):
	def test_patch_has_expected_cuda_moe_probe_changes(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-cuda-moe-probe-and-startup-cache-skip.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text)
		self.assertEqual(errors, [])
