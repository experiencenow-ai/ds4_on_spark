from __future__ import annotations

import json
from pathlib import Path
import unittest

from ds4_transfer.service import TransferRequest, TransferTopology, plan_transfer, run_transfer

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "profiles" / "transfer" / "spark_200g.json"


class TransferPlanTests(unittest.TestCase):
    def test_transfer_plan_uses_200g_bulk_copy(self) -> None:
        topology = TransferTopology.load(TOPOLOGY)
        request = TransferRequest.from_json(
            {
                "format": "ds4-transfer-request-v1",
                "request_id": "t0",
                "source_node": "spark0",
                "source_path": "/mnt/data/batch/",
                "destination_node": "spark4",
                "destination_path": "/mnt/data/batch/",
            }
        )
        plan = plan_transfer(topology, request)
        self.assertEqual(plan["method"], "parallel_nc_fanout_200g_v1")
        self.assertEqual(plan["direct_data_path"], "spark0-200g -> spark4-200g")
        self.assertIn("ds4_transfer.fast_copy", plan["argv"])
        self.assertIn("--jobs-per-edge", plan["argv"])
        self.assertEqual(plan["destination_fabric_ip"], "10.10.100.14")
        self.assertEqual(plan["configured_rails"], 0)

    def test_adjacent_transfer_plan_uses_configured_dual_rails(self) -> None:
        topology = TransferTopology.load(TOPOLOGY)
        request = TransferRequest.from_json(
            {
                "format": "ds4-transfer-request-v1",
                "request_id": "t-rails",
                "source_node": "spark0",
                "source_path": "/mnt/data/batch/",
                "destination_node": "spark1",
                "destination_path": "/mnt/data/batch/",
            }
        )
        plan = plan_transfer(topology, request)
        self.assertEqual(plan["configured_rails"], 2)
        rails = topology.get_fabric_rails("spark0", "spark1")
        self.assertEqual([(rail.source_ip, rail.destination_ip) for rail in rails], [("10.10.1.1", "10.10.1.2"), ("10.10.2.1", "10.10.2.2")])
        reverse = topology.get_fabric_rails("spark1", "spark0")
        self.assertEqual([(rail.source_ip, rail.destination_ip) for rail in reverse], [("10.10.1.2", "10.10.1.1"), ("10.10.2.2", "10.10.2.1")])

    def test_transfer_rejects_disallowed_paths(self) -> None:
        topology = TransferTopology.load(TOPOLOGY)
        request = TransferRequest.from_json(
            {
                "format": "ds4-transfer-request-v1",
                "source_node": "spark0",
                "source_path": "/etc/passwd",
                "destination_node": "spark1",
                "destination_path": "/mnt/data/passwd",
            }
        )
        with self.assertRaises(ValueError):
            plan_transfer(topology, request)

    def test_dry_run_returns_plan_without_executing(self) -> None:
        topology = TransferTopology.load(TOPOLOGY)
        request = TransferRequest.from_json(
            {
                "format": "ds4-transfer-request-v1",
                "source_node": "spark2",
                "source_path": "/tmp/source/",
                "destination_node": "spark3",
                "destination_path": "/tmp/destination/",
            }
        )
        result = run_transfer(topology, request, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "planned")
        self.assertEqual(result["plan"]["source_node"], "spark2")


if __name__ == "__main__":
    unittest.main()
