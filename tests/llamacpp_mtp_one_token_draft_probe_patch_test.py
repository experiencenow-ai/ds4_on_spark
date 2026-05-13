import unittest

from scripts import verify_llamacpp_mtp_one_token_draft_probe_patch as verify


class LlamacppMtpOneTokenDraftProbePatchTest(unittest.TestCase):
	def test_skeleton_patch_9222e55_passes_verifier(self) -> None:
		path = "docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch"
		with open(path, "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text, patch_path=path)
		self.assertEqual(errors, [])

	def test_skeleton_patch_94073e2_passes_verifier(self) -> None:
		path = "docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-one-token-draft-probe-skeleton.patch"
		with open(path, "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text, patch_path=path)
		self.assertEqual(errors, [])

