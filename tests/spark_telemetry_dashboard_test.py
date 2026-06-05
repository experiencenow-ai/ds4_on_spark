import json
import tempfile
import unittest
from pathlib import Path

from scripts import spark_telemetry_dashboard as dashboard


class SparkTelemetryDashboardTest(unittest.TestCase):
    def setUp(self):
        dashboard.reset_node_error_streaks()

    def test_snapshot_summarizes_busy_and_hot_nodes(self):
        payload = {
            "updated_iso": "2026-05-26T00:00:00+00:00",
            "updated_unix": 1,
            "queue": {
                "local_queue_source": "ds4-api:http://10.20.0.10:8700",
                "local_queue_depth": 12,
                "local_queue_running": 5,
                "local_queue_queued": 3,
            },
            "nodes": {
                "spark0": {"sample_count": 2, "last_gpu_util_pct": 96, "last_gpu_power_w": 37, "last_cpu_util_pct": 40, "last_vllm_metrics_up": 1, "last_vllm_requests_running": 4, "last_vllm_requests_waiting": 0, "last_vllm_kv_cache_pct": 50, "last_vllm_tokens_per_s": 2, "last_vllm_prompt_tokens_per_s": 7, "last_vllm_generation_tokens_per_s": 2, "last_vllm_prompt_tokens_cached_per_s": 3, "last_vllm_prompt_cache_hit_pct": 42},
                "spark1": {"sample_count": 2, "last_gpu_util_pct": 96, "last_gpu_power_w": 13, "last_gpu_temp_c": 82, "last_vllm_requests_running": 0, "last_vllm_requests_waiting": 0, "last_vllm_kv_cache_pct": 92},
                "spark2": {"sample_count": 2, "stale_data": 1, "fetch_error": "ssh timed out", "last_gpu_util_pct": 10},
                "spark6": {"sample_count": 0, "error": "ssh timed out"},
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snap = dashboard.build_snapshot(str(path))
        self.assertTrue(snap["ok"])
        self.assertEqual(snap["reachable_nodes"], 4)
        self.assertEqual(snap["busy_gpu_nodes"], 2)
        self.assertEqual(snap["hot_nodes"], 1)
        self.assertEqual(snap["vllm_running"], 5)
        self.assertEqual(snap["vllm_waiting"], 3)
        self.assertEqual(snap["queue_depth"], 12)
        self.assertEqual(snap["input_tok_s"], 7)
        self.assertEqual(snap["output_tok_s"], 2)
        self.assertEqual(snap["tok_s"], 9)
        self.assertEqual(snap["total_gpu_power_w"], 50.0)
        self.assertTrue(snap["gpu_known"])
        self.assertEqual(snap["avg_gpu_pct"], 67.33)
        self.assertEqual(snap["active_nodes"], 2)
        self.assertTrue(snap["kv_known"])
        self.assertTrue(snap["cache_known"])
        self.assertEqual([node["state"] for node in snap["nodes"]], ["busy", "hot", "warn", "warn"])
        self.assertEqual(snap["nodes"][2]["state_label"], "stale")
        self.assertEqual(snap["nodes"][3]["state_label"], "checking")
        self.assertEqual(snap["nodes"][0]["local_q_depth"], 12)
        self.assertTrue(snap["nodes"][0]["local_queue_known"])
        self.assertEqual(snap["nodes"][1]["tok_s"], 0)
        self.assertEqual(snap["nodes"][0]["cpu_pct"], 800)
        self.assertEqual(snap["nodes"][0]["gpu_power_w"], 37)

    def test_node_down_requires_three_distinct_error_snapshots(self):
        payload = {
            "updated_iso": "2026-05-26T00:00:00+00:00",
            "updated_unix": 1,
            "nodes": {"spark6": {"sample_count": 0, "error": "ssh timed out"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            first = dashboard.build_snapshot(str(path))
            second_same_snapshot = dashboard.build_snapshot(str(path))
            payload["updated_unix"] = 2
            path.write_text(json.dumps(payload), encoding="utf-8")
            second = dashboard.build_snapshot(str(path))
            payload["updated_unix"] = 3
            path.write_text(json.dumps(payload), encoding="utf-8")
            third = dashboard.build_snapshot(str(path))
        self.assertEqual(first["nodes"][0]["state"], "warn")
        self.assertEqual(first["nodes"][0]["error_streak"], 1)
        self.assertEqual(second_same_snapshot["nodes"][0]["state"], "warn")
        self.assertEqual(second_same_snapshot["nodes"][0]["error_streak"], 1)
        self.assertEqual(second["nodes"][0]["state"], "warn")
        self.assertEqual(second["nodes"][0]["error_streak"], 2)
        self.assertEqual(third["nodes"][0]["state"], "down")
        self.assertEqual(third["nodes"][0]["error_streak"], 3)

    def test_snapshot_marks_global_ds4_api_queue_as_known(self):
        payload = {
            "updated_iso": "2026-05-26T00:00:00+00:00",
            "updated_unix": 1,
            "queue": {
                "local_queue_source": "ds4-api:http://10.20.0.10:8700",
                "local_queue_depth": 2,
                "local_queue_running": 2,
                "local_queue_queued": 1,
                "local_queue_ds_services": "dsv4_flash_pp8,qwen27_bf16_pp8",
                "local_queue_ds_service_count": 2,
                "local_queue_ds_model_count": 6,
                "local_queue_last_service": "dsv4_flash_pp8",
                "local_queue_kv_shards": 8,
                "local_queue_kv_by_node": "spark0:dsv4_flash_pp8",
            },
            "nodes": {"spark0": {"sample_count": 1, "last_gpu_util_pct": 0, "last_vllm_metrics_up": 0}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snap = dashboard.build_snapshot(str(path))
        self.assertTrue(snap["nodes"][0]["local_queue_known"])
        self.assertTrue(snap["nodes"][0]["kv_known"])
        self.assertEqual(snap["nodes"][0]["kv_label"],"api")
        self.assertEqual(snap["nodes"][0]["ds_service_id"],"dsv4_flash_pp8")
        self.assertEqual(snap["nodes"][0]["input_tok_s"],0.0)
        self.assertEqual(snap["nodes"][0]["output_tok_s"],0.0)
        self.assertEqual(snap["vllm_running"],2.0)
        self.assertEqual(snap["vllm_waiting"],1.0)
        self.assertEqual(snap["queue_depth"],2.0)
        self.assertTrue(snap["ds_services_known"])
        self.assertEqual(snap["ds_service_count"],2.0)
        self.assertEqual(snap["ds_model_count"],6.0)
        self.assertEqual(snap["ds_last_service"],"dsv4_flash_pp8")
        self.assertEqual(snap["ds_kv_shards"],8.0)

    def test_snapshot_uses_current_ds4_stage_payload_for_node_telemetry(self):
        payload = {
            "updated_iso": "2026-05-26T00:00:00+00:00",
            "updated_unix": 1,
            "queue": {
                "local_queue_source": "ds4-api:http://10.20.0.10:8700",
                "local_queue_stage_service_by_node": "spark0:dsv4_flash_pp8",
                "local_queue_stage_sample_count_by_node": "spark0:8",
                "local_queue_stage_gpu_util_by_node": "spark0:96",
                "local_queue_stage_gpu_temp_by_node": "spark0:47",
                "local_queue_stage_gpu_power_by_node": "spark0:17.5",
                "local_queue_stage_cpu_pct_by_node": "spark0:4",
                "local_queue_stage_mem_pct_by_node": "spark0:85",
                "local_queue_stage_prompt_tok_s_by_node": "spark0:12",
                "local_queue_stage_generation_tok_s_by_node": "spark0:7",
            },
            "nodes": {"spark0": {"sample_count": 0, "error": "ssh timed out"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snap = dashboard.build_snapshot(str(path))
        node = snap["nodes"][0]
        self.assertEqual(node["state"],"warn")
        self.assertEqual(node["state_label"],"stale")
        self.assertEqual(node["sample_count"],8)
        self.assertEqual(node["gpu_pct"],96)
        self.assertEqual(node["gpu_temp_c"],47)
        self.assertEqual(node["gpu_power_w"],17.5)
        self.assertEqual(node["cpu_pct"],80)
        self.assertEqual(node["mem_pct"],85)
        self.assertEqual(node["input_tok_s"],12)
        self.assertEqual(node["output_tok_s"],7)
        self.assertEqual(node["tok_s"],19)
        self.assertEqual(node["ds_service_id"],"dsv4_flash_pp8")

    def test_history_reads_last_csv_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spark2.csv"
            path.write_text(
                "unix_ts,iso_ts,node,gpu_util_pct,gpu_temp_c,gpu_power_w,cpu_util_pct,mem_used_pct,vllm_requests_running,vllm_requests_waiting,vllm_kv_cache_pct,vllm_tokens_per_s,vllm_prompt_tokens_per_s,vllm_generation_tokens_per_s,vllm_prompt_cache_hit_pct,vllm_external_prefix_cache_hit_pct\n"
                "1,2026-05-26T00:00:01+00:00,spark2,10,40,20,5,30,1,0,3,0.5,0.2,0.3,10,0\n"
                "2,2026-05-26T00:00:02+00:00,spark2,20,41,21,6,31,2,1,4,1.5,0.6,0.9,20,5\n"
                "3,2026-05-26T00:00:03+00:00,spark2,30,42,22,7,32,3,2,5,2.5,1.1,1.4,30,10\n",
                encoding="utf-8",
            )
            hist = dashboard.build_history(tmp, "spark2", 2)
        self.assertTrue(hist["ok"])
        self.assertEqual(hist["node"], "spark2")
        self.assertEqual(len(hist["points"]), 2)
        self.assertEqual(hist["points"][0]["iso_ts"], "2026-05-26T00:00:02+00:00")
        self.assertEqual(hist["points"][1]["gpu_pct"], 30)
        self.assertEqual(hist["points"][1]["tok_s"], 2.5)
        self.assertEqual(hist["points"][1]["input_tok_s"], 1.1)
        self.assertEqual(hist["points"][1]["output_tok_s"], 1.4)
        self.assertEqual(hist["points"][1]["cache_hit_pct"], 30)
        self.assertEqual(hist["points"][1]["cpu_pct"], 140)

    def test_history_rejects_invalid_node_name(self):
        hist = dashboard.build_history("/tmp", "../spark2", 2)
        self.assertFalse(hist["ok"])
        self.assertEqual(hist["error"], "invalid node")

    def test_history_skips_repeated_csv_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spark2.csv"
            path.write_text(
                "unix_ts,iso_ts,node,gpu_util_pct,gpu_temp_c,gpu_power_w,cpu_util_pct,mem_used_pct,vllm_requests_running,vllm_requests_waiting,vllm_kv_cache_pct,vllm_tokens_per_s,vllm_prompt_tokens_per_s,vllm_generation_tokens_per_s,vllm_prompt_cache_hit_pct,vllm_external_prefix_cache_hit_pct\n"
                "unix_ts,iso_ts,node,gpu_util_pct,gpu_temp_c,gpu_power_w,cpu_util_pct,mem_used_pct,vllm_requests_running,vllm_requests_waiting,vllm_kv_cache_pct,vllm_tokens_per_s,vllm_prompt_tokens_per_s,vllm_generation_tokens_per_s,vllm_prompt_cache_hit_pct,vllm_external_prefix_cache_hit_pct\n"
                "1,2026-05-26T00:00:01+00:00,spark2,10,40,20,5,30,1,0,3,0.5,0.2,0.3,10,0\n",
                encoding="utf-8",
            )
            hist = dashboard.build_history(tmp, "spark2", 10)
        self.assertEqual(len(hist["points"]), 1)
        self.assertEqual(hist["points"][0]["iso_ts"], "2026-05-26T00:00:01+00:00")

    def test_default_history_limit_is_one_hour(self):
        self.assertEqual(dashboard.history_limit(None), 720)
        self.assertEqual(dashboard.history_limit(""), 720)

    def test_dashboard_uses_persistent_event_stream(self):
        self.assertIn("new EventSource(`/api/stream?node=${node}`)", dashboard.DASHBOARD_HTML)
        self.assertIn('addEventListener("telemetry"', dashboard.DASHBOARD_HTML)
        self.assertNotIn("const REFRESH_MS", dashboard.DASHBOARD_HTML)
        self.assertNotIn("setInterval(", dashboard.DASHBOARD_HTML)

    def test_stream_payload_includes_summary_and_selected_history(self):
        payload = {
            "updated_iso": "2026-05-26T00:00:00+00:00",
            "updated_unix": 1,
            "nodes": {"spark2": {"sample_count": 1, "last_cpu_util_pct": 40}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            nodes_dir = Path(tmp) / "nodes"
            nodes_dir.mkdir()
            summary_path.write_text(json.dumps(payload), encoding="utf-8")
            (nodes_dir / "spark2.csv").write_text(
                "unix_ts,iso_ts,node,gpu_util_pct,gpu_temp_c,gpu_power_w,cpu_util_pct,mem_used_pct,vllm_requests_running,vllm_requests_waiting,vllm_kv_cache_pct,vllm_tokens_per_s,vllm_prompt_tokens_per_s,vllm_generation_tokens_per_s,vllm_prompt_cache_hit_pct,vllm_external_prefix_cache_hit_pct\n"
                "1,2026-05-26T00:00:01+00:00,spark2,10,40,20,40,30,1,0,3,0.5,0.2,0.3,10,0\n",
                encoding="utf-8",
            )
            stream = dashboard.stream_payload(str(summary_path), str(nodes_dir), "", 10)
        self.assertEqual(stream["summary"]["selected_node"], "spark2")
        self.assertEqual(stream["summary"]["nodes"][0]["cpu_pct"], 800)
        self.assertEqual(stream["history"]["node"], "spark2")
        self.assertEqual(stream["history"]["points"][0]["cpu_pct"], 800)

    def test_dashboard_cpu_display_uses_twenty_core_range(self):
        self.assertEqual(dashboard.DISPLAY_CPU_PCT_MAX, 2000)
        self.assertEqual(dashboard.display_cpu_pct(40), 800)
        self.assertIn('"cpu_pct"', dashboard.DASHBOARD_HTML)
        self.assertIn("const CPU_PCT_MAX=2000", dashboard.DASHBOARD_HTML)
        self.assertIn("cpu_pct:CPU_PCT_MAX", dashboard.DASHBOARD_HTML)

    def test_dashboard_card_shows_watts_and_marks_missing_vllm_na(self):
        self.assertIn('Pwr <b>${val(n.gpu_power_w,"W")}</b>', dashboard.DASHBOARD_HTML)
        self.assertIn('Svc <b>${n.ds_service_id||"n/a"}</b>', dashboard.DASHBOARD_HTML)
        self.assertIn('bar("KV",n.kv_pct,"kv",n.kv_known,n.kv_label)', dashboard.DASHBOARD_HTML)
        self.assertIn('function workKnown(n)', dashboard.DASHBOARD_HTML)
        self.assertIn('n.vllm_metrics_up||n.local_queue_known', dashboard.DASHBOARD_HTML)
        self.assertIn('workKnown(n)?val(n[key],unit):"n/a"', dashboard.DASHBOARD_HTML)
        self.assertIn('n.vllm_metrics_up?pct(n.cache_hit_pct):"n/a"', dashboard.DASHBOARD_HTML)

    def test_dashboard_summary_combines_tokens_and_shows_total_power(self):
        self.assertIn('grid-template-columns:repeat(7,minmax(110px,1fr))', dashboard.DASHBOARD_HTML)
        self.assertIn('metric("GPU Avg",d.gpu_known?pct(d.avg_gpu_pct):"n/a")', dashboard.DASHBOARD_HTML)
        self.assertIn('metric("DS Models",d.ds_services_known?`${fmt(d.ds_service_count)} svc`:"n/a")', dashboard.DASHBOARD_HTML)
        self.assertIn('metric("Tok/s In/Out",`${val(d.input_tok_s)} / ${val(d.output_tok_s)}`)', dashboard.DASHBOARD_HTML)
        self.assertIn('metric("Total Power",val(d.total_gpu_power_w,"W"))', dashboard.DASHBOARD_HTML)
        self.assertNotIn('metric("In tok/s"', dashboard.DASHBOARD_HTML)
        self.assertNotIn('metric("Out tok/s"', dashboard.DASHBOARD_HTML)
        self.assertNotIn('metric("Cache hit"', dashboard.DASHBOARD_HTML)


if __name__ == "__main__":
    unittest.main()
