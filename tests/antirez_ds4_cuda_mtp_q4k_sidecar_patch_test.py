import unittest

from scripts import verify_antirez_ds4_cuda_mtp_q4k_sidecar_patch as verify


class AntirezDs4CudaMtpQ4kSidecarPatchTest(unittest.TestCase):
	def test_patch_has_expected_mtp_sidecar_changes(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text)
		self.assertEqual(errors, [])
