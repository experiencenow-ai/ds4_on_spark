import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_mtp_target_suffix_verify_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-mtp-target-suffix-verify-k2.patch")


class AntirezDs4MtpTargetSuffixVerifyPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		self.assertEqual(verify.validate_patch_text(PATCH.read_text(encoding="utf-8")), [])

	def test_rejects_missing_suffix_api(self) -> None:
		errors = verify.validate_patch_text("+draft_n == 4\n")
		self.assertTrue(any("ds4_mtp_decode2_stats" in item for item in errors))
		self.assertTrue(any("forbidden" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
