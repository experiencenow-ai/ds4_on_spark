import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_vllm_batched_marlin_prototype as validator


def valid_obj() -> dict:
	obj = {
		"format": validator.FORMAT,
		"artifact_sha256": "",
		"prototype_id": "unit",
		"model_id": "deepseek-ai/DeepSeek-V4-Flash",
		"runtime_version": "0.1.dev",
		"runtime_commit": "dda4668",
		"patch_id": "ds4-vllm-no-dp-batched-marlin-prototype",
		"env_flag": "DS4_VLLM_FORCE_NO_DP_BATCHED_MARLIN=1",
		"selected_backend": "BATCHED_MARLIN",
		"activation_format": "BatchedExperts",
		"prepare_finalize": "BatchedPrepareAndFinalize",
		"patch_files": sorted(validator.REQUIRED_PATCH_FILES),
		"baseline_c512_aggregate_tps": 174.19031762627782,
		"startup_status": "passed",
		"measured_c512_aggregate_tps": 220.0,
		"speedup_vs_baseline": 220.0 / 174.19031762627782,
	}
	obj["artifact_sha256"] = validator.canonical_hash(obj)
	return(obj)


class VllmBatchedMarlinPrototypeTest(unittest.TestCase):
	def test_passed_measurement_validates(self) -> None:
		obj = valid_obj()
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertEqual(errors, [])

	def test_hash_mismatch_rejected(self) -> None:
		obj = valid_obj()
		obj["runtime_commit"] = "tampered"
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("artifact_sha256" in item for item in errors))

	def test_failed_requires_blocker(self) -> None:
		obj = valid_obj()
		obj["startup_status"] = "failed"
		obj.pop("measured_c512_aggregate_tps")
		obj.pop("speedup_vs_baseline")
		obj["artifact_sha256"] = validator.canonical_hash(obj)
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("blocker_kind" in item for item in errors))
		self.assertTrue(any("blocker_detail" in item for item in errors))
		self.assertTrue(any("error_signature" in item for item in errors))

	def test_failed_rejects_measured_tps(self) -> None:
		obj = valid_obj()
		obj["startup_status"] = "failed"
		obj["blocker_kind"] = "shape_contract_mismatch"
		obj["blocker_detail"] = "unit"
		obj["error_signature"] = "unit"
		obj["artifact_sha256"] = validator.canonical_hash(obj)
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("must not report measured" in item for item in errors))

	def test_missing_patch_file_rejected(self) -> None:
		obj = copy.deepcopy(valid_obj())
		obj["patch_files"] = obj["patch_files"][:-1]
		obj["artifact_sha256"] = validator.canonical_hash(obj)
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("patch_files missing" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
