import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_vllm_moe_code_audit as audit_validator


class VllmMoeCodeAuditTest(unittest.TestCase):
	def test_fixture_validates(self) -> None:
		result = audit_validator.validate_paths(audit_validator.default_paths())
		self.assertTrue(result["ok"], result["errors"])

	def test_hash_mismatch_rejected(self) -> None:
		path = Path("fixture.json")
		obj = audit_validator.load(audit_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["runtime_commit"] = "tampered"
		errors = audit_validator.validate(obj, path)
		self.assertTrue(any("artifact_sha256" in item for item in errors))

	def test_selected_backend_must_match_measured_marlin(self) -> None:
		path = Path("fixture.json")
		obj = audit_validator.load(audit_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["measured_selected_backend"] = "BATCHED_MARLIN"
		obj["artifact_sha256"] = audit_validator.canonical_hash(obj)
		errors = audit_validator.validate(obj, path)
		self.assertTrue(any("measured_selected_backend" in item for item in errors))

	def test_missing_batched_activation_evidence_rejected(self) -> None:
		path = Path("fixture.json")
		obj = audit_validator.load(audit_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		obj["source_evidence"] = [item for item in obj["source_evidence"] if item["id"] != "batched_activation_gating"]
		obj["artifact_sha256"] = audit_validator.canonical_hash(obj)
		errors = audit_validator.validate(obj, path)
		self.assertTrue(any("source_evidence missing ids" in item for item in errors))

	def test_direct_slice_tile8_copy_must_be_marked_not_portable(self) -> None:
		path = Path("fixture.json")
		obj = audit_validator.load(audit_validator.default_paths()[0])
		obj = copy.deepcopy(obj)
		for item in obj["opportunities"]:
			if item["id"] == "copy_ds4_slice_tile8_kernel_directly":
				item["status"] = "reachable"
		obj["artifact_sha256"] = audit_validator.canonical_hash(obj)
		errors = audit_validator.validate(obj, path)
		self.assertTrue(any("not_portable" in item for item in errors))


if __name__ == "__main__":
	unittest.main()
