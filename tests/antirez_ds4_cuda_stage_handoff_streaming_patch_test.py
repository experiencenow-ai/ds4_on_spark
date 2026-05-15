import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_cuda_stage_handoff_streaming_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-stage-handoff-streaming.patch")


class AntirezDs4CudaStageHandoffStreamingPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		self.assertEqual(verify.validate_patch_text(PATCH.read_text(encoding="utf-8")), [])

	def test_missing_iter_metrics_fail(self) -> None:
		text = PATCH.read_text(encoding="utf-8").replace("iter_ms", "")
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("iter_ms" in error for error in errors))


if __name__ == "__main__":
	unittest.main()
