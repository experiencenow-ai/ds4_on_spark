import unittest

from scripts import verify_antirez_ds4_mtp_one_token_oracle_patch as verify


class AntirezDs4MtpOneTokenOraclePatchTest(unittest.TestCase):
	def test_patch_has_expected_oracle_json_plumbing(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-mtp-one-token-json-probe.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text)
		self.assertEqual(errors, [])

