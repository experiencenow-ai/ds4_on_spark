import json
import subprocess
import unittest
from pathlib import Path


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-moe-slice-tile8-gateup.patch")


class AntirezDs4CudaMoeSliceTile8PatchTest(unittest.TestCase):
	def test_patch_contains_slice_tile8_gateup_path(self) -> None:
		rc = subprocess.run(
			[
				"python3",
				"scripts/verify_antirez_ds4_cuda_moe_slice_tile8_patch.py",
				"--patch",
				str(PATCH),
			],
			text=True,
			capture_output=True,
			check=False,
		)
		self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
		obj = json.loads(rc.stdout)
		self.assertTrue(obj["ok"])
		self.assertEqual(obj["missing"], [])


if __name__ == "__main__":
	unittest.main()
