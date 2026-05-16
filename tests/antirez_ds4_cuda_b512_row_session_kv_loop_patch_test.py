import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_cuda_b512_row_session_kv_loop_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-b512-row-session-kv-loop.patch")


class AntirezDs4CudaB512RowSessionKvLoopPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		self.assertEqual(verify.validate_patch_text(PATCH.read_text(encoding="utf-8")), [])

	def test_rejects_single_sequence_rows_shortcut(self) -> None:
		text = PATCH.read_text(encoding="utf-8") + "\nsingle_sequence_rows\n"
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("single_sequence_rows" in error for error in errors))

	def test_missing_row_session_cache_fails(self) -> None:
		text = PATCH.read_text(encoding="utf-8").replace("batch_layer_raw_cache", "")
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("batch_layer_raw_cache" in error for error in errors))


if __name__ == "__main__":
	unittest.main()
