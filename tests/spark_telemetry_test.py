import unittest
import os
import tempfile
from unittest import mock

from scripts import spark_node_telemetry_monitor as node_mon
from scripts import spark_telemetry_collect as collect
from scripts import spark_telemetry_common as telemetry


def telemetry_row(**kwargs):
    row = {field:"0" for field in node_mon.CSV_FIELDS}
    row.update({
        "unix_ts": "1",
        "iso_ts": "2026-05-24T00:00:01+00:00",
        "node": "spark0",
        "hostname": "h",
        "gpu_index": "0",
        "gpu_name": "NVIDIA GB10",
        "gpu_pstate": "P0",
        "error": "",
    })
    row.update({k:str(v) for k,v in kwargs.items()})
    return(",".join(row[field] for field in node_mon.CSV_FIELDS))


class SparkTelemetryTest(unittest.TestCase):
    def test_default_spark_nodes_are_all_eight(self):
        expected = tuple("spark%d" % i for i in range(8))
        self.assertEqual(telemetry.SPARK_NODES, expected)
        self.assertEqual(telemetry.parse_nodes("all"), list(expected))
        self.assertEqual(telemetry.parse_nodes(""), list(expected))
        self.assertEqual(telemetry.parse_node_targets("spark4=spark4-10g,spark5"), [("spark4","spark4-10g"), ("spark5","spark5")])
        self.assertEqual(collect.telemetry.DEFAULT_NODES, ",".join(expected))
        self.assertEqual(node_mon.CSV_FIELDS, telemetry.CSV_FIELDS)
        self.assertIn("vllm_requests_running", telemetry.CSV_FIELDS)
        self.assertIn("vllm_requests_per_s", telemetry.CSV_FIELDS)
        self.assertIn("vllm_tokens_per_s", telemetry.CSV_FIELDS)
        self.assertIn("vllm_prompt_tokens_per_s", telemetry.CSV_FIELDS)
        self.assertIn("vllm_prompt_cache_hit_pct", telemetry.CSV_FIELDS)
        self.assertIn("vllm_external_prefix_cache_hit_pct", telemetry.CSV_FIELDS)
        self.assertIn("power.limit", telemetry.BASE_GPU_FIELDS)
        self.assertIn("gpu_power_known", telemetry.CSV_FIELDS)
        self.assertIn("gpu_power_raw_w", telemetry.CSV_FIELDS)
        self.assertNotIn("local_queue_source", telemetry.CSV_FIELDS)

    def test_gpu_power_status_rejects_unsupported_nvml_power(self):
        status = telemetry.gpu_power_status(11.0,0.0,96.0)
        self.assertEqual(status["gpu_power_w"],0.0)
        self.assertEqual(status["gpu_power_raw_w"],11.0)
        self.assertEqual(status["gpu_power_known"],0)
        self.assertEqual(status["gpu_power_reason"],"nvml-power-limit-unavailable")

    def test_gpu_power_status_rejects_low_power_at_high_util(self):
        status = telemetry.gpu_power_status(11.0,120.0,96.0)
        self.assertEqual(status["gpu_power_w"],0.0)
        self.assertEqual(status["gpu_power_raw_w"],11.0)
        self.assertEqual(status["gpu_power_known"],0)
        self.assertEqual(status["gpu_power_reason"],"nvml-power-sanity-failed")

    def test_gpu_power_status_accepts_supported_power(self):
        status = telemetry.gpu_power_status(81.5,120.0,96.0)
        self.assertEqual(status["gpu_power_w"],81.5)
        self.assertEqual(status["gpu_power_raw_w"],81.5)
        self.assertEqual(status["gpu_power_known"],1)
        self.assertEqual(status["gpu_power_reason"],"")

    def test_cpu_pct_uses_idle_delta(self):
        self.assertEqual(node_mon.cpu_pct((100,40),(200,70)),70.0)

    def test_net_rates_use_byte_delta(self):
        rates = node_mon.net_rates((1000,2000),(2250,2600),0.5)
        self.assertEqual(rates["net_rx_mbps"],0.02)
        self.assertEqual(rates["net_tx_mbps"],0.0096)

    def test_collect_accepts_launchd_fast_fetch_args(self):
        with mock.patch("sys.argv", ["spark_telemetry_collect.py","--ssh-control-dir","/tmp/ds4mux","--ssh-control-persist","600","--fetch-workers","8"]):
            args = collect.parse_args()
        self.assertEqual(args.ssh_control_dir,"/tmp/ds4mux")
        self.assertEqual(args.ssh_control_persist,600)
        self.assertEqual(args.fetch_workers,8)

    def test_fetch_node_uses_control_master_options(self):
        calls = []
        class Result:
            returncode = 0
            stdout = "unix_ts,iso_ts\n"
            stderr = ""
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return(Result())
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(collect.subprocess,"run",fake_run):
                collect.fetch_node("spark0","/tmp/ds4_telemetry",8,720,"spark0-10g",tmp,600)
        self.assertIn("ControlMaster=auto", calls[0])
        self.assertIn("ControlPersist=600s", calls[0])
        self.assertIn("ControlPath=%s" % os.path.join(tmp,"t-%C"), calls[0])

    def test_collect_summary_counts_hot_gpu_samples(self):
        text = "\n".join([
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=1,cpu_util_pct=10,mem_used_pct=50,gpu_util_pct=96,gpu_power_w=40,gpu_power_raw_w=40,gpu_power_limit_w=120,gpu_power_known=1,gpu_temp_c=81,thermal_max_c=67,root_disk_used_pct=71,net_rx_mbps=1.5,net_tx_mbps=2.5),
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=2,iso_ts="2026-05-24T00:00:02+00:00",cpu_util_pct=30,mem_used_pct=60,gpu_util_pct=10,gpu_power_w=12,gpu_power_raw_w=12,gpu_power_limit_w=120,gpu_power_known=1,gpu_temp_c=63,thermal_max_c=65,root_disk_used_pct=72,net_rx_mbps=3.0,net_tx_mbps=4.0),
        ])
        rows = collect.read_rows(text)
        summary = collect.summarize_node(rows,"")
        self.assertEqual(summary["sample_count"],2)
        self.assertEqual(summary["last_gpu_util_pct"],10.0)
        self.assertEqual(summary["gpu_samples_ge_90"],1)
        self.assertEqual(summary["pct_gpu_samples_ge_90"],50.0)
        self.assertEqual(summary["gpu_temp_samples_ge_80"],1)
        self.assertEqual(summary["last_gpu_temp_c"],63.0)
        self.assertEqual(summary["last_gpu_power_w"],12.0)
        self.assertEqual(summary["last_gpu_power_raw_w"],12.0)
        self.assertEqual(summary["last_gpu_power_limit_w"],120.0)
        self.assertEqual(summary["last_gpu_power_known"],1.0)
        self.assertEqual(summary["last_thermal_max_c"],65.0)
        self.assertEqual(summary["last_root_disk_used_pct"],72.0)
        self.assertEqual(summary["net_tx_mbps"]["max"],4.0)
        self.assertEqual(summary["cpu_util_pct"]["avg"],20.0)

    def test_collect_markdown_summary_includes_gpu_watts(self):
        text = "\n".join([
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=1,gpu_util_pct=10,gpu_power_w=12,gpu_power_raw_w=12,gpu_power_limit_w=120,gpu_power_known=1,gpu_temp_c=63),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            rows = collect.read_rows(text)
            collect.write_combined(tmp,{"spark0":rows},{},{})
            with open(os.path.join(tmp,"cluster_summary.md"),encoding="utf-8") as fp:
                md = fp.read()
        self.assertIn("| node | samples | gpu % | gpu C | gpu W |", md)
        self.assertIn("| spark0 | 1 | 10.00 | 63.00 | 12.00 |", md)

    def test_collect_markdown_summary_marks_untrusted_gpu_watts_na(self):
        text = "\n".join([
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=1,gpu_util_pct=96,gpu_power_w=0,gpu_power_raw_w=11,gpu_power_limit_w=0,gpu_power_known=0,gpu_power_reason="nvml-power-limit-unavailable",gpu_temp_c=63),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            rows = collect.read_rows(text)
            collect.write_combined(tmp,{"spark0":rows},{},{})
            with open(os.path.join(tmp,"cluster_summary.md"),encoding="utf-8") as fp:
                md = fp.read()
        self.assertIn("| spark0 | 1 | 96.00 | 63.00 | n/a |", md)

    def test_collect_markdown_summary_marks_missing_sources_na(self):
        with tempfile.TemporaryDirectory() as tmp:
            collect.write_combined(tmp,{"spark0":[]},{"spark0":"ssh timed out"},{})
            with open(os.path.join(tmp,"cluster_summary.md"),encoding="utf-8") as fp:
                md = fp.read()
        self.assertIn("| spark0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a |", md)

    def test_collect_summary_marks_cached_fetch_failures_as_stale(self):
        text = "\n".join([
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=1,cpu_util_pct=10,mem_used_pct=50,gpu_util_pct=20),
        ])
        rows = collect.read_rows(text)
        summary = collect.summarize_node(rows,"","ssh timed out",True)
        self.assertEqual(summary["sample_count"],1)
        self.assertEqual(summary["error"],"")
        self.assertEqual(summary["fetch_error"],"ssh timed out")
        self.assertEqual(summary["stale_data"],1)

    def test_collect_summary_uses_latest_good_gpu_sample_after_timeout(self):
        text = "\n".join([
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=1,cpu_util_pct=10,mem_used_pct=50,gpu_util_pct=20,gpu_power_w=12,gpu_power_raw_w=12,gpu_power_limit_w=120,gpu_power_known=1,gpu_temp_c=63),
            telemetry_row(unix_ts=2,iso_ts="2026-05-24T00:00:02+00:00",cpu_util_pct=30,mem_used_pct=60,gpu_index=-1,gpu_util_pct=0,gpu_power_w=0,gpu_temp_c=0,error="nvidia-smi timeout"),
        ])
        rows = collect.read_rows(text)
        summary = collect.summarize_node(rows,"")
        self.assertEqual(summary["last_cpu_util_pct"],30.0)
        self.assertEqual(summary["last_mem_used_pct"],60.0)
        self.assertEqual(summary["last_gpu_util_pct"],20.0)
        self.assertEqual(summary["last_gpu_power_w"],12.0)
        self.assertEqual(summary["last_gpu_temp_c"],63.0)

    def test_vllm_metrics_parser_sums_live_depth(self):
        text = "\n".join([
            'vllm:num_requests_running{model_name="m"} 7.0',
            'vllm:num_requests_waiting{model_name="m"} 2.0',
            'vllm:kv_cache_usage_perc{model_name="m"} 0.25',
            'vllm:prompt_tokens_total{model_name="m"} 123.0',
            'vllm:generation_tokens_total{model_name="m"} 456.0',
        ])
        old = node_mon.read_text_url
        try:
            node_mon.read_text_url = lambda url,timeout: (text,"")
            metrics = node_mon.read_vllm_metrics("http://x/metrics",1.0)
        finally:
            node_mon.read_text_url = old
        self.assertEqual(metrics["vllm_metrics_up"],1)
        self.assertEqual(metrics["vllm_requests_running"],7.0)
        self.assertEqual(metrics["vllm_requests_waiting"],2.0)
        self.assertEqual(metrics["vllm_kv_cache_pct"],25.0)
        self.assertEqual(metrics["vllm_generation_tokens_total"],456.0)

    def test_vllm_metrics_parser_handles_source_tokens_and_rates(self):
        text = "\n".join([
            'vllm:num_requests_running 3.0',
            'vllm:num_requests_waiting 2.0',
            'vllm:request_success_total 12.0',
            'vllm:gpu_cache_usage_perc{model_name="m"} 45.0',
            'vllm:prompt_tokens_by_source_total{source="local_compute"} 10.0',
            'vllm:prompt_tokens_by_source_total{source="local_cache_hit"} 20.0',
            'vllm:prompt_tokens_by_source_total{source="external_kv_transfer"} 5.0',
            'vllm:prompt_tokens_cached_total{model_name="m"} 25.0',
            'vllm:prefix_cache_queries_total{model_name="m"} 100.0',
            'vllm:prefix_cache_hits_total{model_name="m"} 40.0',
            'vllm:external_prefix_cache_queries_total{model_name="m"} 20.0',
            'vllm:external_prefix_cache_hits_total{model_name="m"} 10.0',
            'vllm:generation_tokens_total{model_name="m"} 40.0',
        ])
        old = node_mon.read_text_url
        try:
            node_mon.read_text_url = lambda url,timeout: (text,"")
            prev = {
                "unix_ts": 90.0,
                "vllm_requests_total": 2.0,
                "vllm_tokens_total": 20.0,
                "vllm_prompt_tokens_total": 10.0,
                "vllm_generation_tokens_total": 10.0,
                "vllm_prompt_tokens_cached_total": 5.0,
                "vllm_prefix_cache_queries_total": 80.0,
                "vllm_prefix_cache_hits_total": 30.0,
                "vllm_external_prefix_cache_queries_total": 15.0,
                "vllm_external_prefix_cache_hits_total": 5.0,
            }
            metrics = node_mon.read_vllm_metrics("http://x/metrics",1.0,prev,100.0)
        finally:
            node_mon.read_text_url = old
        self.assertEqual(metrics["vllm_metrics_up"],1)
        self.assertEqual(metrics["vllm_requests_running"],3.0)
        self.assertEqual(metrics["vllm_requests_waiting"],2.0)
        self.assertEqual(metrics["vllm_requests_total"],12.0)
        self.assertEqual(metrics["vllm_requests_per_s"],1.0)
        self.assertEqual(metrics["vllm_kv_cache_pct"],45.0)
        self.assertEqual(metrics["vllm_prompt_tokens_total"],35.0)
        self.assertEqual(metrics["vllm_prompt_tokens_local_cache_hit_total"],20.0)
        self.assertEqual(metrics["vllm_tokens_total"],75.0)
        self.assertEqual(metrics["vllm_tokens_per_s"],5.5)
        self.assertEqual(metrics["vllm_prompt_tokens_per_s"],2.5)
        self.assertEqual(metrics["vllm_generation_tokens_per_s"],3.0)
        self.assertEqual(metrics["vllm_prompt_tokens_cached_per_s"],2.0)
        self.assertEqual(metrics["vllm_prompt_cache_hit_pct"],80.0)
        self.assertEqual(metrics["vllm_prefix_cache_hit_pct"],50.0)
        self.assertEqual(metrics["vllm_external_prefix_cache_hit_pct"],100.0)

    def test_gateway_reads_current_coordinator_api(self):
        def fake_read_json(url,timeout):
            if url.endswith("/health"):
                return({"ok": True},"")
            if url.endswith("/ds4/dispatcher/status"):
                return({"running": True, "last_work_at": 90.0, "last_claimed_service_id": "dsv4_flash_pp8"},"")
            if url.endswith("/ds4/queue/status"):
                return({"format": "ds4-inference-queue-v1", "state_counts": {"queued": 2, "running": 1, "completed": 5, "failed": 1}},"")
            return({},"bad url")
        old_read = node_mon.read_json_url
        old_time = node_mon.time.time
        try:
            node_mon.read_json_url = fake_read_json
            node_mon.time.time = lambda: 100.0
            gateway = node_mon.read_gateway("http://127.0.0.1:8700",1.0)
        finally:
            node_mon.read_json_url = old_read
            node_mon.time.time = old_time
        self.assertEqual(gateway["ds4_gateway_up"],1)
        self.assertEqual(gateway["ds4_gateway_active"],1)
        self.assertEqual(gateway["ds4_gateway_current_model"],"dsv4_flash_pp8")
        self.assertEqual(gateway["ds4_gateway_idle_s"],10.0)
        self.assertEqual(gateway["ds4_gateway_cpu_pending"],2)
        self.assertEqual(gateway["ds4_gateway_cpu_active"],1)
        self.assertEqual(gateway["ds4_gateway_cpu_completed"],5)
        self.assertEqual(gateway["ds4_gateway_cpu_failed"],1)

    def test_ds4_api_queue_reads_coordinator_status(self):
        old = telemetry.read_json_url
        def fake_read_json(url,timeout):
            if url.endswith("/ds4/queue/status"):
                return({
                    "format": "ds4-inference-queue-v1",
                    "state_counts": {"queued": 3, "running": 2, "completed": 7, "failed": 1},
                    "pipeline_status": {"kv_shards": [
                        {"node_id": "spark0", "service_id": "dsv4_flash_pp8", "entries": 2, "bytes": 64},
                        {"node_id": "spark1", "service_id": "dsv4_flash_pp8", "entries": 3, "bytes": 96},
                    ], "stages": [
                        {"node_id": "spark0", "service_id": "dsv4_flash_pp8", "reported_at": 100.0, "payload": {"sample_count": 2, "last_gpu_util_pct": 91, "last_gpu_power_w": 25, "last_gpu_power_raw_w": 25, "last_gpu_power_limit_w": 120, "last_gpu_power_known": 1, "last_gpu_power_source": "nvml.power.draw", "last_gpu_temp_c": 48, "last_cpu_util_pct": 40, "last_mem_used_pct": 50}},
                        {"node_id": "spark1", "service_id": "dsv4_flash_pp8", "reported_at": 101.0, "payload": {"sample_count": 3, "last_gpu_util_pct": 92, "last_gpu_power_w": 26, "last_gpu_power_raw_w": 26, "last_gpu_power_limit_w": 120, "last_gpu_power_known": 1, "last_gpu_power_source": "nvml.power.draw", "last_gpu_temp_c": 49, "last_cpu_util_pct": 41, "last_mem_used_pct": 51}},
                    ]},
                },"")
            if url.endswith("/ds4/dispatcher/status"):
                return({
                    "running": True,
                    "last_claimed_service_id": "dsv4_flash_pp8",
                    "pending_by_service": {"dsv4_flash_pp8": 3},
                    "resident_multimodel": True,
                    "resident_service_targets": {"dsv4_flash_pp8": 128, "qwen27_bf16_pp8": 12},
                },"")
            if url.endswith("/v1/models"):
                return({"data": [
                    {"id": "deepseek-ai/DeepSeek-V4-Flash", "ds4_service_id": "dsv4_flash_pp8"},
                    {"id": "Qwen/Qwen3.6-27B", "ds4_service_id": "qwen27_bf16_pp8"},
                    {"id": "profile-only"},
                ]},"")
            return({},"bad url")
        try:
            telemetry.read_json_url = fake_read_json
            q = telemetry.read_ds4_api_queue("http://10.20.0.10:8700",1.0)
        finally:
            telemetry.read_json_url = old
        self.assertEqual(q["local_queue_source"],"ds4-api:http://10.20.0.10:8700")
        self.assertEqual(q["local_queue_api_up"],1)
        self.assertEqual(q["local_queue_depth"],5)
        self.assertEqual(q["local_queue_queued"],3)
        self.assertEqual(q["local_queue_running"],2)
        self.assertEqual(q["local_queue_completed"],7)
        self.assertEqual(q["local_queue_failed"],1)
        self.assertEqual(q["local_queue_ds_service_count"],2)
        self.assertEqual(q["local_queue_ds_model_count"],3)
        self.assertEqual(q["local_queue_last_service"],"dsv4_flash_pp8")
        self.assertEqual(q["local_queue_resident_multimodel"],1)
        self.assertIn("dsv4_flash_pp8", q["local_queue_ds_services"])
        self.assertIn("qwen27_bf16_pp8", q["local_queue_ds_services"])
        self.assertIn("dsv4_flash_pp8:3", q["local_queue_pending_by_service"])
        self.assertIn("qwen27_bf16_pp8:12", q["local_queue_resident_service_targets"])
        self.assertEqual(q["local_queue_kv_shards"],2)
        self.assertEqual(q["local_queue_kv_entries"],5)
        self.assertEqual(q["local_queue_kv_bytes"],160)
        self.assertEqual(q["local_queue_kv_by_node"],"spark0:dsv4_flash_pp8;spark1:dsv4_flash_pp8")
        self.assertEqual(q["local_queue_stage_service_by_node"],"spark0:dsv4_flash_pp8;spark1:dsv4_flash_pp8")
        self.assertIn("spark0:91", q["local_queue_stage_gpu_util_by_node"])
        self.assertIn("spark1:26", q["local_queue_stage_gpu_power_by_node"])
        self.assertIn("spark1:26", q["local_queue_stage_gpu_power_raw_by_node"])
        self.assertIn("spark1:1", q["local_queue_stage_gpu_power_known_by_node"])
        self.assertIn("spark1:nvml.power.draw", q["local_queue_stage_gpu_power_source_by_node"])

if __name__ == "__main__":
    unittest.main()
