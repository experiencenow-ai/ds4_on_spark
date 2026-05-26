import json
import tempfile
import unittest
from pathlib import Path

from scripts import spark_telemetry_dashboard as dashboard


class SparkTelemetryDashboardTest(unittest.TestCase):
    def test_snapshot_summarizes_busy_and_hot_nodes(self):
        payload = {
            "updated_iso": "2026-05-26T00:00:00+00:00",
            "updated_unix": 1,
            "queue": {"local_queue_depth": 12},
            "nodes": {
                "spark0": {"sample_count": 2, "last_gpu_util_pct": 96, "last_vllm_requests_running": 4, "last_vllm_requests_waiting": 0, "last_vllm_kv_cache_pct": 50},
                "spark1": {"sample_count": 2, "last_gpu_util_pct": 96, "last_gpu_temp_c": 82, "last_vllm_requests_running": 1, "last_vllm_requests_waiting": 3, "last_vllm_kv_cache_pct": 92},
                "spark6": {"sample_count": 0, "error": "ssh timed out"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snap = dashboard.build_snapshot(str(path))
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["reachable_nodes"], 2)
        self.assertEqual(snap["busy_gpu_nodes"], 2)
        self.assertEqual(snap["hot_nodes"], 1)
        self.assertEqual(snap["vllm_running"], 5)
        self.assertEqual(snap["vllm_waiting"], 3)
        self.assertEqual(snap["queue_depth"], 12)
        self.assertEqual([node["state"] for node in snap["nodes"]], ["busy", "hot", "down"])


if __name__ == "__main__":
    unittest.main()
