import unittest
from pathlib import Path

from scripts import verify_antirez_ds4_cuda_stage_handoff_patch as verify


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-stage-handoff-files.patch")


class AntirezDs4CudaStageHandoffPatchTest(unittest.TestCase):
	def test_patch_contract(self) -> None:
		self.assertEqual(verify.validate_patch_text(PATCH.read_text(encoding="utf-8")), [])

	def test_missing_boundary_input_env_fails(self) -> None:
		text = PATCH.read_text(encoding="utf-8").replace("DS4_CUDA_STACK_PROBE_INPUT_HC_FILE", "")
		errors = verify.validate_patch_text(text)
		self.assertTrue(any("INPUT_HC_FILE" in error for error in errors))


if __name__ == "__main__":
	unittest.main()
