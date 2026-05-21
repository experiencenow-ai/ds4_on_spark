import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_vllm_gb10_flashinfer_moe as validator


def valid_obj() -> dict:
	obj = {
		"format": validator.FORMAT,
		"artifact_sha256": "",
		"probe_id": "unit",
		"model_id": "deepseek-ai/DeepSeek-V4-Flash",
		"runtime_version": "0.1.dev",
		"runtime_commit": "dda4668",
		"patch_id": "ds4-vllm-gb10-flashinfer-trtllm-moe",
		"env_flag": "DS4_VLLM_ENABLE_GB10_FLASHINFER_TRTLLM_MOE=1",
		"patch_files": [validator.PATCH_FILE],
		"device_name": "NVIDIA GB10",
		"device_capability": [12, 1],
		"flashinfer_available": True,
		"platform_family100_before_patch": False,
		"supports_trtllm_mxfp4_before_patch": False,
		"supports_trtllm_mxfp4_after_patch": True,
		"baseline_c512_aggregate_tps": 174.19031762627782,
		"startup_status": "not_run",
		"blocker_kind": "unit",
		"blocker_detail": "unit",
	}
	obj["artifact_sha256"] = validator.canonical_hash(obj)
	return(obj)


class VllmGb10FlashinferMoeTest(unittest.TestCase):
	def test_probe_validates(self) -> None:
		obj = valid_obj()
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertEqual(errors, [])

	def test_hash_mismatch_rejected(self) -> None:
		obj = valid_obj()
		obj["runtime_commit"] = "tampered"
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("artifact_sha256" in item for item in errors))

	def test_missing_patch_file_rejected(self) -> None:
		obj = copy.deepcopy(valid_obj())
		obj["patch_files"] = []
		obj["artifact_sha256"] = validator.canonical_hash(obj)
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("patch_files" in item for item in errors))

	def test_failed_requires_blocker(self) -> None:
		obj = valid_obj()
		obj["startup_status"] = "failed"
		obj.pop("blocker_kind")
		obj["artifact_sha256"] = validator.canonical_hash(obj)
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("blocker_kind" in item for item in errors))

	def test_passed_requires_measurement(self) -> None:
		obj = valid_obj()
		obj["startup_status"] = "passed"
		obj.pop("blocker_kind")
		obj.pop("blocker_detail")
		obj["artifact_sha256"] = validator.canonical_hash(obj)
		errors = validator.validate(obj, Path("fixture.json"))
		self.assertTrue(any("measured_c512" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
