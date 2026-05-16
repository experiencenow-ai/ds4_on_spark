import json
import subprocess
import unittest
from pathlib import Path


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-moe-direct-sum6-down.patch")


class AntirezDs4CudaMoeDirectSum6DownPatchTest(unittest.TestCase):
	def test_patch_contains_direct_sum6_down_path(self) -> None:
		rc = subprocess.run(
			[
				"python3",
				"scripts/verify_antirez_ds4_cuda_moe_direct_sum6_down_patch.py",
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
