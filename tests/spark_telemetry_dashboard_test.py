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
            "queue": {
                "local_queue_depth": 12,
                "local_queue_by_node": "spark0:5;spark1:4",
                "local_queue_running_by_node": "spark0:4;spark1:1",
                "local_queue_queued_by_node": "spark0:1;spark1:3",
                "local_queue_completion_tok_s": 9.5,
                "local_queue_completion_tok_s_by_node": "spark0:6.5;spark1:3",
            },
            "nodes": {
                "spark0": {"sample_count": 2, "last_gpu_util_pct": 96, "last_vllm_metrics_up": 1, "last_vllm_requests_running": 4, "last_vllm_requests_waiting": 0, "last_vllm_kv_cache_pct": 50, "last_vllm_tokens_per_s": 2},
                "spark1": {"sample_count": 2, "last_gpu_util_pct": 96, "last_gpu_temp_c": 82, "last_vllm_requests_running": 0, "last_vllm_requests_waiting": 0, "last_vllm_kv_cache_pct": 92},
                "spark2": {"sample_count": 2, "stale_data": 1, "fetch_error": "ssh timed out", "last_gpu_util_pct": 10},
                "spark6": {"sample_count": 0, "error": "ssh timed out"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snap = dashboard.build_snapshot(str(path))
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["reachable_nodes"], 3)
        self.assertEqual(snap["busy_gpu_nodes"], 2)
        self.assertEqual(snap["hot_nodes"], 1)
        self.assertEqual(snap["vllm_running"], 5)
        self.assertEqual(snap["vllm_waiting"], 3)
        self.assertEqual(snap["queue_depth"], 12)
        self.assertEqual(snap["tok_s"], 9.5)
        self.assertTrue(snap["kv_known"])
        self.assertEqual([node["state"] for node in snap["nodes"]], ["busy", "hot", "warn", "down"])
        self.assertEqual(snap["nodes"][2]["state_label"], "stale")
        self.assertEqual(snap["nodes"][0]["local_q_depth"], 5)
        self.assertEqual(snap["nodes"][1]["tok_s"], 3)

    def test_history_reads_last_csv_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spark2.csv"
            path.write_text(
                "unix_ts,iso_ts,node,gpu_util_pct,gpu_temp_c,gpu_power_w,cpu_util_pct,mem_used_pct,vllm_requests_running,vllm_requests_waiting,vllm_kv_cache_pct,local_queue_depth,vllm_tokens_per_s\n"
                "1,2026-05-26T00:00:01+00:00,spark2,10,40,20,5,30,1,0,3,7,0.5\n"
                "2,2026-05-26T00:00:02+00:00,spark2,20,41,21,6,31,2,1,4,8,1.5\n"
                "3,2026-05-26T00:00:03+00:00,spark2,30,42,22,7,32,3,2,5,9,2.5\n",
                encoding="utf-8",
            )
            hist = dashboard.build_history(tmp, "spark2", 2)
        self.assertTrue(hist["ok"])
        self.assertEqual(hist["node"], "spark2")
        self.assertEqual(len(hist["points"]), 2)
        self.assertEqual(hist["points"][0]["iso_ts"], "2026-05-26T00:00:02+00:00")
        self.assertEqual(hist["points"][1]["gpu_pct"], 30)
        self.assertEqual(hist["points"][1]["queue_depth"], 9)
        self.assertEqual(hist["points"][1]["tok_s"], 2.5)

    def test_history_rejects_invalid_node_name(self):
        hist = dashboard.build_history("/tmp", "../spark2", 2)
        self.assertFalse(hist["ok"])
        self.assertEqual(hist["error"], "invalid node")

    def test_default_history_limit_is_one_hour(self):
        self.assertEqual(dashboard.history_limit(None), 720)
        self.assertEqual(dashboard.history_limit(""), 720)


if __name__ == "__main__":
    unittest.main()
