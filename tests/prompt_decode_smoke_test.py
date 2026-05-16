import copy
import unittest
from pathlib import Path

from scripts import build_ds4_prompt_decode_smoke as smoke


FIX = Path("fixtures/prompt_decode_smoke")


class PromptDecodeSmokeTest(unittest.TestCase):
	def test_prompt_decode_smoke_fixtures_validate(self) -> None:
		for path in sorted(FIX.glob("*.json")):
			with self.subTest(path=path.name):
				obj = smoke.load_json(path)
				self.assertEqual(smoke.validate_artifact(obj), [])

	def test_blocked_smoke_cannot_claim_production_eligibility(self) -> None:
		obj = smoke.load_json(FIX / "dsv4_b512_slice_tile8_prompt_decode_smoke_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["production_generation_eligible"] = True
		obj["artifact_sha256"] = smoke.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = smoke.validate_artifact(obj)
		self.assertTrue(any("production_generation_eligible" in item for item in errors))

	def test_committed_token_smoke_requires_token_hash(self) -> None:
		obj = smoke.load_json(FIX / "dsv4_b512_slice_tile8_prompt_decode_smoke_20260516.example.json")
		obj = copy.deepcopy(obj)
		obj["token_commit_status"] = "committed"
		obj["committed_token_ids"] = [1]
		obj["token_hash"] = ""
		obj["blocker_kind"] = "none"
		obj["blocker_detail"] = ""
		obj["artifact_sha256"] = smoke.artifact_sha256(obj)
		obj["artifact_hash"] = obj["artifact_sha256"]
		errors = smoke.validate_artifact(obj)
		self.assertTrue(any("token_hash" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
