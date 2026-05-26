import unittest
import os
import sqlite3
import tempfile

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
        self.assertIn("local_queue_depth", telemetry.CSV_FIELDS)

    def test_cpu_pct_uses_idle_delta(self):
        self.assertEqual(node_mon.cpu_pct((100,40),(200,70)),70.0)

    def test_net_rates_use_byte_delta(self):
        rates = node_mon.net_rates((1000,2000),(2250,2600),0.5)
        self.assertEqual(rates["net_rx_mbps"],0.02)
        self.assertEqual(rates["net_tx_mbps"],0.0096)

    def test_collect_summary_counts_hot_gpu_samples(self):
        text = "\n".join([
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=1,cpu_util_pct=10,mem_used_pct=50,gpu_util_pct=96,gpu_power_w=40,gpu_temp_c=81,thermal_max_c=67,root_disk_used_pct=71,net_rx_mbps=1.5,net_tx_mbps=2.5),
            ",".join(node_mon.CSV_FIELDS),
            telemetry_row(unix_ts=2,iso_ts="2026-05-24T00:00:02+00:00",cpu_util_pct=30,mem_used_pct=60,gpu_util_pct=10,gpu_power_w=12,gpu_temp_c=63,thermal_max_c=65,root_disk_used_pct=72,net_rx_mbps=3.0,net_tx_mbps=4.0),
        ])
        rows = collect.read_rows(text)
        summary = collect.summarize_node(rows,"")
        self.assertEqual(summary["sample_count"],2)
        self.assertEqual(summary["last_gpu_util_pct"],10.0)
        self.assertEqual(summary["gpu_samples_ge_90"],1)
        self.assertEqual(summary["pct_gpu_samples_ge_90"],50.0)
        self.assertEqual(summary["gpu_temp_samples_ge_80"],1)
        self.assertEqual(summary["last_gpu_temp_c"],63.0)
        self.assertEqual(summary["last_thermal_max_c"],65.0)
        self.assertEqual(summary["last_root_disk_used_pct"],72.0)
        self.assertEqual(summary["net_tx_mbps"]["max"],4.0)
        self.assertEqual(summary["cpu_util_pct"]["avg"],20.0)

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

    def test_local_queue_depth_reads_sqlite_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp,"queue.sqlite3")
            with sqlite3.connect(db) as conn:
                conn.execute("create table requests (state text, request_kind text, selected_node_id text)")
                conn.executemany("insert into requests values (?,?,?)", [
                    ("queued","model","spark0"),
                    ("running","model","spark0"),
                    ("running","cpu","spark1"),
                    ("completed","model","spark0"),
                    ("failed","model","spark2"),
                ])
            q = telemetry.read_local_queue(db,"")
        self.assertEqual(q["local_queue_depth"],3)
        self.assertEqual(q["local_queue_model_depth"],2)
        self.assertEqual(q["local_queue_cpu_depth"],1)
        self.assertEqual(q["local_queue_completed"],1)
        self.assertIn("spark0:2", q["local_queue_by_node"])


if __name__ == "__main__":
    unittest.main()
