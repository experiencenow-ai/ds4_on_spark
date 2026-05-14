import unittest

from scripts import verify_antirez_ds4_cuda_moe_batched_expert_tile_slices_patch as verify


class AntirezDs4CudaMoeBatchedExpertTileSlicesPatchTest(unittest.TestCase):
	def test_patch_has_expected_batched_expert_tile_slice_changes(self) -> None:
		with open("docs/antirez-patches/ds4-3630e64-cuda-moe-batched-expert-tile-slices.patch", "r", encoding="utf-8") as f:
			patch_text = f.read()
		errors = verify.validate_patch_text(patch_text)
		self.assertEqual(errors, [])
