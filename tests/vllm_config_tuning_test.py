import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_vllm_config_tuning as tuning_validator


class VllmConfigTuningTest(unittest.TestCase):
	def test_fixture_validates(self) -> None:
		result = tuning_validator.validate_paths(tuning_validator.default_paths())
		self.assertTrue(result["ok"], result["errors"])

	def test_hash_mismatch_rejected(self) -> None:
		path = Path("fixture.json")
		obj = tuning_validator.load(tuning_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["model_id"] = "tampered"
		errors = tuning_validator.validate(obj, path)
		self.assertTrue(any("artifact_sha256" in item for item in errors))

	def test_rejected_attempt_cannot_be_faster_than_selected(self) -> None:
		path = Path("fixture.json")
		obj = tuning_validator.load(tuning_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["attempts"][0]["tokens_per_second_by_concurrency"] = {"512": 999.0}
		obj["attempts"][0]["startup_status"] = "passed"
		obj["attempts"][0]["safety_status"] = "passed"
		obj["artifact_sha256"] = tuning_validator.canonical_hash(obj)
		errors = tuning_validator.validate(obj, path)
		self.assertTrue(any("selected config must not be slower" in item for item in errors))

	def test_unsafe_faster_attempt_not_selected(self) -> None:
		path = Path("fixture.json")
		obj = tuning_validator.load(tuning_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["attempts"][0]["tokens_per_second_by_concurrency"] = {"512": 999.0}
		obj["attempts"][0]["startup_status"] = "passed"
		obj["attempts"][0]["safety_status"] = "failed_after_stress"
		obj["artifact_sha256"] = tuning_validator.canonical_hash(obj)
		errors = tuning_validator.validate(obj, path)
		self.assertFalse(any("selected config must not be slower" in item for item in errors), errors)

	def test_missing_raw_artifact_rejected(self) -> None:
		path = Path("fixture.json")
		obj = tuning_validator.load(tuning_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["attempts"][1]["raw_artifact"] = "fixtures/vllm_config_tuning/missing.raw.json"
		obj["artifact_sha256"] = tuning_validator.canonical_hash(obj)
		errors = tuning_validator.validate(obj, path)
		self.assertTrue(any("raw artifact missing" in item for item in errors))

	def test_c256_only_selected_config_allowed(self) -> None:
		path = Path("fixture.json")
		obj = tuning_validator.load(tuning_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["selected_config"]["max_num_seqs"] = 256
		obj["selected_config"]["tokens_per_second_at_c256"] = 333.0
		obj["selected_config"]["tokens_per_second_at_c512"] = None
		obj["attempts"][0]["tokens_per_second_by_concurrency"] = {"256": 333.0}
		obj["attempts"][0]["startup_status"] = "passed"
		obj["attempts"][0]["safety_status"] = "passed"
		obj["artifact_sha256"] = tuning_validator.canonical_hash(obj)
		errors = tuning_validator.validate(obj, path)
		self.assertFalse(any("tokens_per_second_at_c512" in item for item in errors), errors)


if __name__ == "__main__":
	unittest.main()
