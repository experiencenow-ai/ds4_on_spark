import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_spark_reachability_report as validator


FIXTURE = Path("fixtures/spark_reachability/spark_reachability_report_20260517.example.json")


class SparkReachabilityReportTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validator.validate_paths([FIXTURE])
        self.assertTrue(result["ok"], result["errors"])

    def test_report_covers_required_hosts_and_checks(self) -> None:
        report = validator.load_json(FIXTURE)
        for host in ("192.0.2.11", "192.0.2.12", "aitopatom-9ab9.local", "spark0.local", "spark1.local", "spark2.local"):
            self.assertIn(host, report["expected_hosts"])
            self.assertIn(host, report["dns_results"])
            self.assertIn(host, report["mdns_results"])
            self.assertIn(host, report["ping_results"])
            self.assertIn(host, report["ssh_results"])
            self.assertIn(host, report["known_hosts_status"])
        self.assertIn("spark0@spark0.local", report["configured_inventory_hosts"])
        self.assertIn("192.0.2.11", report["direct_ip_results"])
        self.assertIn("192.0.2.12", report["direct_ip_results"])
        self.assertIn(report["blocker_kind"], validator.BLOCKER_KINDS)
        self.assertIn("Spark", report["recommended_fix"])

    def test_artifact_hash_detects_tampering(self) -> None:
        report = validator.load_json(FIXTURE)
        tampered = copy.deepcopy(report)
        tampered["blocker_kind"] = "host_unreachable"
        errors = validator.validate_report(tampered)
        self.assertTrue(any("artifact_sha256" in item for item in errors))

    def test_rejects_missing_required_fields(self) -> None:
        report = validator.load_json(FIXTURE)
        report.pop("ssh_results")
        errors = validator.validate_report(report)
        self.assertTrue(any("missing required field: ssh_results" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
