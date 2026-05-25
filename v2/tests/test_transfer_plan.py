from __future__ import annotations

import json
from pathlib import Path
import unittest

from ds4_transfer.service import TransferRequest, TransferTopology, plan_transfer, run_transfer

ROOT = Path(__file__).resolve().parents[1]
TOPOLOGY = ROOT / "profiles" / "transfer" / "spark_200g.json"


class TransferPlanTests(unittest.TestCase):
    def test_transfer_plan_runs_rsync_on_source_node_for_direct_data_path(self) -> None:
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
        self.assertEqual(plan["method"], "source_initiated_rsync_over_ssh_no_compress")
        self.assertEqual(plan["direct_data_path"], "spark0 -> spark4")
        self.assertEqual(plan["argv"][:4], ["ssh", "-T", "-o", "Compression=no"])
        self.assertIn("spark0", plan["argv"])
        self.assertIn("spark4:/mnt/data/batch/", plan["argv"])
        self.assertIn("--no-compress", plan["argv"])

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
