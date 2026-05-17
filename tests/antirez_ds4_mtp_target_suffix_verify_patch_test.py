import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_mtp_target_suffix_verify_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-mtp-target-suffix-verify-k2.patch")


class AntirezDs4MtpTargetSuffixVerifyPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		self.assertEqual(verify.validate_patch_text(PATCH.read_text(encoding="utf-8")), [])

	def test_rejects_missing_suffix_api(self) -> None:
		errors = verify.validate_patch_text("+draft_n == 4\n")
		self.assertTrue(any("use_target_suffix2" in item for item in errors))
		self.assertTrue(any("forbidden" in item for item in errors))

	def test_rejects_k2_without_k3_direct_path(self) -> None:
		text = "+const bool use_target_suffix2 =\n+static int metal_graph_try_mtp_suffix2_direct(\n"
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("metal_graph_try_mtp_suffix3_direct" in item for item in errors))

	def test_rejects_k3_without_prefix3_frontier(self) -> None:
		text = "\n".join([
			"+const bool use_target_suffix2 =",
			"+static int metal_graph_try_mtp_suffix2_direct(",
			"+static int metal_graph_try_mtp_suffix3_direct(",
			"+metal_graph_encode_output_head_suffix4_top3",
			"+drafted=3 committed=3",
		])
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("spec_frontier_commit_prefix3_graph" in item for item in errors))

	def test_rejects_k2_without_top1_continuation_head(self) -> None:
		text = PATCH.read_text(encoding="utf-8").replace("metal_graph_encode_output_head_suffix3_top3", "")
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("metal_graph_encode_output_head_suffix3_top3" in item for item in errors))

	def test_rejects_unsafe_row2_skip_readback_knob(self) -> None:
		text = PATCH.read_text(encoding="utf-8") + "\n+getenv(\"DS4_MTP_ROW2_SKIP_LOGITS_READBACK\")\n"
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("DS4_MTP_ROW2_SKIP_LOGITS_READBACK" in item for item in errors))

	def test_rejects_trace_mode_pending_argmax_bypass(self) -> None:
		text = PATCH.read_text(encoding="utf-8") + "\n+trace_top ? NULL : &pending_argmax\n"
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("trace_top ? NULL" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
