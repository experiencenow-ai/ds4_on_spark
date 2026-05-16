import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_token_commit_profile as profile


FIX = Path("fixtures/token_commit_profile")


class TokenCommitProfileTest(unittest.TestCase):
	def test_token_commit_profile_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = profile.load_json(path)
				self.assertEqual(profile.validate_artifact(obj), [])

	def test_full_vocab_profile_identifies_output_head_bottleneck(self) -> None:
		obj = profile.load_json(FIX / "ds4_b512_full_vocab_token_commit_profile_20260516.example.json")
		self.assertEqual(obj["bottleneck_component"], "full_batch_head_projection")
		self.assertGreater(max(obj["output_head_ms"]), 1000.0)
		self.assertLess(max(obj["top1_argmax_ms"]), 1.0)

	def test_tampered_hash_fails_validation(self) -> None:
		obj = profile.load_json(FIX / "ds4_b512_constrained_token_commit_profile_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["token_hash"] = "fnv64:0000000000000000"
		obj["artifact_sha256"] = profile.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = profile.validate_artifact(obj)
		self.assertTrue(any("token_hash" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
