import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_vllm_pp_runtime_probe as validate


FIXTURE = Path("fixtures/vllm_pp_runtime_probe/ds4_vllm_pp3_mgmt_gb10_indexer_fallback_20260520.example.json")


class VllmPpRuntimeProbeTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validate.validate_paths([FIXTURE])
        self.assertEqual(result["errors"], [])

    def test_passed_artifact_requires_token_hash(self) -> None:
        obj = validate.load_json(FIXTURE)
        obj.pop("token_hash")
        errors = validate.validate_artifact(obj, FIXTURE)
        self.assertTrue(any("token_hash" in item for item in errors))

    def test_token_ids_must_match_generated_tokens(self) -> None:
        obj = copy.deepcopy(validate.load_json(FIXTURE))
        obj["generated_tokens"] = 2
        errors = validate.validate_artifact(obj, FIXTURE)
        self.assertTrue(any("token_ids length" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
