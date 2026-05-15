import unittest

from scripts import verify_antirez_ds4_cuda_multi_model_cache_patch as verify
from scripts import verify_antirez_ds4_mtp_decode2_default_patch as verify_decode2


class AntirezDs4CudaMultiModelCachePatchTest(unittest.TestCase):
	def test_patch_has_expected_keying_changes(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text)
		self.assertEqual(errors, [])

	def test_decode2_default_patch_has_expected_verifier_gate(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-mtp-decode2-default-verifier.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify_decode2.validate_patch_text(patch_text)
		self.assertEqual(errors, [])
