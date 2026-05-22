import copy
import tempfile
import unittest
from pathlib import Path

from scripts import run_ds4_spark_reachability_report as runner
from scripts import validate_ds4_spark_reachability_report as validator


FIXTURE = Path("fixtures/spark_reachability/spark_reachability_report_20260517.example.json")
EIGHT_NODE_FIXTURE = Path("fixtures/spark_reachability/spark_reachability_8nodes_20260522.example.json")


class SparkReachabilityReportTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validator.validate_paths([FIXTURE, EIGHT_NODE_FIXTURE])
        self.assertTrue(result["ok"], result["errors"])

    def test_eight_node_fixture_has_successful_ssh_for_all_sparks(self) -> None:
        report = validator.load_json(EIGHT_NODE_FIXTURE)
        self.assertEqual(report["expected_hosts"], [
            "spark0-wifi",
            "spark1-wifi",
            "spark2-wifi",
            "spark3-wifi",
            "spark4-wifi",
            "spark5-wifi",
            "spark6-wifi",
            "spark7",
        ])
        for host in report["expected_hosts"]:
            self.assertEqual(report["ssh_results"][host]["status"], "success")

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

    def test_inventory_reader_can_skip_legacy_default_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            targets, configured = runner._read_inventory_targets(Path(tmp), "spark0", False)
        self.assertEqual(targets, {})
        self.assertEqual(configured, [])


if __name__ == "__main__":
    unittest.main()
