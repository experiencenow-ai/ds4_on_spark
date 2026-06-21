from __future__ import annotations

import json
from pathlib import Path
from argparse import Namespace
import unittest

from ds4_transfer.fast_copy import FileItem, _is_local_node, _port_for_shard, _stripe_count_for_item, _striped_remote_python, _validate_port_ranges
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

    def test_transfer_topology_includes_new_sparks_and_hf_cache_roots(self) -> None:
        topology = TransferTopology.load(TOPOLOGY)
        self.assertEqual(topology.get_node("spark8").fabric_ip, "10.10.100.18")
        self.assertEqual(topology.get_node("spark9").fabric_ip, "10.10.100.19")
        self.assertEqual(topology.get_node("sparka").fabric_ip, "10.10.100.20")
        self.assertEqual(topology.get_node("sparkb").fabric_ip, "10.10.100.21")
        self.assertEqual(topology.get_node("sparkc").fabric_ip, "10.10.100.22")
        self.assertIn("/home/spark8/.cache/huggingface", topology.get_node("spark8").root_allowlist)
        self.assertIn((("spark8", "spark9"),), topology.fanout_stages)
        request = TransferRequest.from_json(
            {
                "format": "ds4-transfer-request-v1",
                "request_id": "new-nodes",
                "source_node": "spark8",
                "source_path": "/home/spark8/models",
                "destination_node": "sparkc",
                "destination_path": "/home/sparkc/models",
            }
        )
        plan = plan_transfer(topology, request)
        self.assertEqual(plan["direct_data_path"], "spark8-200g -> sparkc-200g")
        self.assertEqual(plan["destination_fabric_ip"], "10.10.100.22")

    def test_striped_remote_python_preserves_home_expansion(self) -> None:
        command = _striped_remote_python(Namespace(remote_v2_dir="~/src/ds4_on_spark/v2"))
        self.assertIn("cd ~/src/ds4_on_spark/v2;", command)
        self.assertNotIn("'~/", command)

    def test_striped_port_ranges_do_not_overlap_between_shards(self) -> None:
        args = Namespace(port_base=49300, jobs_per_edge=16, striped_file_stripes=8)
        ports = [_port_for_shard(args, 0, 0, slot) for slot in range(args.jobs_per_edge)]
        self.assertEqual(ports[0], 49300)
        self.assertEqual(ports[1], 49308)
        self.assertEqual(ports[-1], 49420)
        self.assertEqual(_port_for_shard(args, 0, 1, 0), 49500)
        _validate_port_ranges(args, [[("spark7", "spark8")]])
        bad = Namespace(port_base=49300, jobs_per_edge=32, striped_file_stripes=8)
        with self.assertRaises(ValueError):
            _validate_port_ranges(bad, [[("spark7", "spark8")]])

    def test_local_node_marks_self_for_non_ssh_source_commands(self) -> None:
        self.assertTrue(_is_local_node(Namespace(local_node="spark8"), "spark8"))
        self.assertFalse(_is_local_node(Namespace(local_node="spark8"), "spark9"))

    def test_small_files_use_single_python_stripe(self) -> None:
        args = Namespace(striped_file_threshold_bytes=64 * 1024 * 1024, striped_file_stripes=8)
        self.assertEqual(_stripe_count_for_item(args, FileItem(".gitattributes", 1521)), 1)
        self.assertEqual(_stripe_count_for_item(args, FileItem("model-00001-of-00087.safetensors", 5_368_709_120)), 8)


if __name__ == "__main__":
    unittest.main()
