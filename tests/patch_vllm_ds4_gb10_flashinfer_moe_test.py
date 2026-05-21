import tempfile
import unittest
from pathlib import Path

from scripts import patch_vllm_ds4_gb10_flashinfer_moe as patcher


TRTLLM_MXFP4_MOE = """# SPDX-License-Identifier: Apache-2.0

import torch

from vllm.platforms import current_platform
from vllm.utils.flashinfer import has_flashinfer


class TrtLlmMxfp4ExpertsBase:
    @staticmethod
    def _supports_current_device() -> bool:
        p = current_platform
        return p.is_cuda() and p.is_device_capability_family(100) and has_flashinfer()
"""


class PatchVllmDs4Gb10FlashinferMoeTest(unittest.TestCase):
	def test_patch_unlocks_opt_in_gb10_support(self) -> None:
		once = patcher.patch_trtllm_mxfp4_moe(TRTLLM_MXFP4_MOE)
		twice = patcher.patch_trtllm_mxfp4_moe(once)
		self.assertEqual(once, twice)
		self.assertIn("import os", once)
		self.assertIn("DS4_VLLM_ENABLE_GB10_FLASHINFER_TRTLLM_MOE", once)
		self.assertIn("capability.major != 12", once)
		self.assertIn("GB10", once)
		self.assertIn("p.is_device_capability_family(100)", once)
		self.assertIn("or _ds4_gb10_flashinfer_trtllm_moe_enabled()", once)

	def test_patch_package_dir_writes_backup(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			target = root / "model_executor" / "layers" / "fused_moe" / "experts" / "trtllm_mxfp4_moe.py"
			target.parent.mkdir(parents=True)
			target.write_text(TRTLLM_MXFP4_MOE, encoding="utf-8")
			result = patcher.apply_patch(root, backup_suffix=".bak", write=True)
			self.assertTrue(result["changed"])
			self.assertEqual(result["env_flag"], "DS4_VLLM_ENABLE_GB10_FLASHINFER_TRTLLM_MOE=1")
			self.assertTrue((target.with_name(target.name + ".bak")).exists())
			result2 = patcher.apply_patch(root, backup_suffix=".bak", write=True)
			self.assertFalse(result2["changed"])


if __name__ == "__main__":
	unittest.main()
