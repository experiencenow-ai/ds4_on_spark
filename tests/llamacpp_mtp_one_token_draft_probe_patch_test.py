import subprocess
import sys
import unittest


class LlamaCppMtpOneTokenDraftProbePatchTest(unittest.TestCase):
	def _verify(self, patch_path: str) -> None:
		proc = subprocess.run(
			[sys.executable, "scripts/verify_llamacpp_mtp_one_token_draft_probe_patch.py", "--patch", patch_path],
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			check=False,
		)
		if proc.returncode != 0:
			self.fail(f"patch verify failed for {patch_path}: rc={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")

	def test_patch_94073e2_verifies(self) -> None:
		self._verify(
			"docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-94073e2-mtp-one-token-draft-probe-skeleton.patch"
		)

	def test_patch_9222e55_verifies(self) -> None:
		self._verify(
			"docs/llamacpp-patches/kamnxt-llamacpp-deepseek-v4-flash-cuda-spark-9222e55-mtp-one-token-draft-probe-skeleton.patch"
		)

