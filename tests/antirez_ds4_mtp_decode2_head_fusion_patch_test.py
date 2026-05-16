import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_mtp_decode2_head_fusion_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-mtp-decode2-head-fusion.patch")


class AntirezDs4MtpDecode2HeadFusionPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		self.assertEqual(verify.validate_patch_text(PATCH.read_text(encoding="utf-8")), [])

	def test_missing_fused_batch_head_fails(self) -> None:
		text = PATCH.read_text(encoding="utf-8").replace("metal_graph_encode_output_head_batch", "")
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("metal_graph_encode_output_head_batch" in error for error in errors))


if __name__ == "__main__":
	unittest.main()
