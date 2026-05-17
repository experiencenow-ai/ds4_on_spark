import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_spark_access_contract as validator


FIXTURE = Path("fixtures/spark_access_contract/spark_access_contract_20260517.example.json")


class SparkAccessContractTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validator.validate_paths([FIXTURE])
        self.assertTrue(result["ok"], result["errors"])

    def test_access_contract_uses_known_good_path(self) -> None:
        contract = validator.load_json(FIXTURE)
        self.assertEqual(contract["access_mode"], "known_good_ssh")
        self.assertIn("spark0@aitopatom-9ab9.local", contract["ssh_results"])
        self.assertIn("spark_probe_aitopatom_9ab9_local", contract["probe_results"])
        self.assertEqual(contract["ssh_results"]["spark0@aitopatom-9ab9.local"]["status"], "success")
        self.assertTrue(contract["access_ok"])
        self.assertEqual(contract["blocker_kind"], "none")

    def test_artifact_hash_detects_tampering(self) -> None:
        contract = validator.load_json(FIXTURE)
        tampered = copy.deepcopy(contract)
        tampered["access_ok"] = False
        tampered["blocker_kind"] = "known_good_ssh_failed"
        errors = validator.validate_contract(tampered)
        self.assertTrue(any("artifact_sha256" in item for item in errors))

    def test_access_ok_requires_no_blocker(self) -> None:
        contract = validator.load_json(FIXTURE)
        bad = copy.deepcopy(contract)
        bad["blocker_kind"] = "spark_probe_failed"
        bad["artifact_sha256"] = validator.artifact_sha256(bad)
        bad["artifact_hash"] = bad["artifact_sha256"]
        errors = validator.validate_contract(bad)
        self.assertTrue(any("access_ok=true" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
