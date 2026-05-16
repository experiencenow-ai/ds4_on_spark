import json
import subprocess
import unittest
from pathlib import Path


PATCH = Path("docs/antirez-patches/ds4-3630e64-cuda-constrained-candidate-dynamic.patch")


class AntirezDs4CudaConstrainedCandidateDynamicPatchTest(unittest.TestCase):
	def test_patch_removes_fixed_256_candidate_cap(self) -> None:
		rc = subprocess.run(
			[
				"python3",
				"scripts/verify_antirez_ds4_cuda_constrained_candidate_dynamic_patch.py",
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
		self.assertEqual(obj["forbidden"], [])
		self.assertEqual(obj["not_removed"], [])

	def test_rejects_old_fixed_array_shape(self) -> None:
		path = Path("/private/tmp/ds4-bad-constrained-cap.patch")
		path.write_text(
			"+    int32_t constrained_ids[256];\n"
			"+    const uint32_t constrained_count = cuda_stack_probe_parse_constrained_ids(constrained_ids, 256u);\n",
			encoding="utf-8",
		)
		rc = subprocess.run(
			[
				"python3",
				"scripts/verify_antirez_ds4_cuda_constrained_candidate_dynamic_patch.py",
				"--patch",
				str(path),
			],
			text=True,
			capture_output=True,
			check=False,
		)
		self.assertNotEqual(rc.returncode, 0)
		obj = json.loads(rc.stdout)
		self.assertIn("int32_t constrained_ids[256]", obj["forbidden"])


if __name__ == "__main__":
	unittest.main()
