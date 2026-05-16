import unittest

from scripts import verify_antirez_ds4_cuda_moe_p2_inner_profile_patch as verify


class AntirezDs4CudaMoeP2InnerProfilePatchTest(unittest.TestCase):
	def test_patch_has_expected_p2_inner_profile_changes(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-cuda-moe-p2-inner-profile.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text)
		self.assertEqual(errors, [])


if __name__ == "__main__":
	unittest.main()
