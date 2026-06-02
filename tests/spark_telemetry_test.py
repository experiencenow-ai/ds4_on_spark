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
        self.assertIn("vllm_tokens_per_s", telemetry.CSV_FIELDS)
        self.assertIn("vllm_prompt_tokens_per_s", telemetry.CSV_FIELDS)
        self.assertIn("vllm_prompt_cache_hit_pct", telemetry.CSV_FIELDS)
        self.assertIn("vllm_external_prefix_cache_hit_pct", telemetry.CSV_FIELDS)
        self.assertIn("local_queue_prompt_tok_s", telemetry.CSV_FIELDS)
        self.assertIn("local_queue_completion_tok_s", telemetry.CSV_FIELDS)

    def test_fetch_node_uses_persistent_ssh_control_socket(self):
        calls = []
        class Result:
            returncode = 0
            stdout = "ok\n"
            stderr = ""
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return(Result())
        old = collect.subprocess.run
        try:
            collect.subprocess.run = fake_run
            with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
                name,text,error = collect.fetch_node("spark3","/tmp/ds4_telemetry",8,720,"spark3-10g",tmp,600)
        finally:
            collect.subprocess.run = old
        self.assertEqual(name,"spark3")
        self.assertEqual(text,"ok\n")
        self.assertEqual(error,"")
        self.assertIn("ControlMaster=auto", calls[0])
        self.assertIn("ControlPersist=600s", calls[0])
        self.assertIn("ControlPath=%s/t-%%C" % tmp, calls[0])
        self.assertIn("spark3-10g", calls[0])

    def test_collect_uses_fresh_cache_without_stale_warning(self):
        old_fetch = collect.fetch_node
        old_time = collect.time.time
        try:
            collect.fetch_node = lambda *args,**kwargs: ("spark3","","ssh timed out")
            collect.time.time = lambda: 100.0
            with tempfile.TemporaryDirectory() as tmp:
                raw_dir = os.path.join(tmp,"nodes")
                os.makedirs(raw_dir)
                with open(os.path.join(raw_dir,"spark3.csv"),"w",encoding="utf-8") as fp:
                    fp.write(",".join(node_mon.CSV_FIELDS) + "\n")
                    fp.write(telemetry_row(unix_ts=95,iso_ts="1970-01-01T00:01:35+00:00",node="spark3") + "\n")
                args = type("Args",(),{
                    "nodes": "spark3",
                    "remote_dir": "/tmp/ds4_telemetry",
                    "out_dir": tmp,
                    "ssh_timeout": 1,
                    "tail_lines": 10,
                    "ssh_control_dir": "",
                    "ssh_control_persist": 0,
                    "fetch_workers": 1,
                    "stale_ok_seconds": 300,
                    "stale_warn_seconds": 30,
                    "queue_db": "",
                    "queue_db_glob": "",
                })()
                summary = collect.collect_once(args)
        finally:
            collect.fetch_node = old_fetch
            collect.time.time = old_time
        self.assertEqual(summary["nodes"]["spark3"]["fetch_error"],"ssh timed out")
        self.assertEqual(summary["nodes"]["spark3"]["stale_data"],0)

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
        self.assertIn("spark0:1", q["local_queue_running_by_node"])

    def test_local_queue_prefers_active_db_and_reports_recent_tok_s(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = os.path.join(tmp,"empty.sqlite3")
            active = os.path.join(tmp,"active.sqlite3")
            with sqlite3.connect(empty) as conn:
                conn.execute("create table requests (state text, request_kind text, selected_node_id text)")
                conn.execute("insert into requests values (?,?,?)", ("completed","model","spark0"))
            with sqlite3.connect(active) as conn:
                conn.execute("create table requests (state text, request_kind text, selected_node_id text, completed_at real, result_json text)")
                conn.execute("insert into requests values (?,?,?,?,?)", ("queued","model","spark0",None,None))
                conn.execute("insert into requests values (?,?,?,?,?)", ("running","model","spark1",None,None))
                conn.execute("insert into requests values (?,?,?,?,?)", ("completed","model","spark1",100.0,'{"usage":{"prompt_tokens":300,"completion_tokens":120}}'))
            os.utime(empty,(200.0,200.0))
            os.utime(active,(100.0,100.0))
            old = telemetry.time.time
            try:
                telemetry.time.time = lambda: 150.0
                q = telemetry.read_local_queue("", "%s,%s" % (empty,active), rate_window_s=60.0)
            finally:
                telemetry.time.time = old
        self.assertEqual(q["local_queue_db"],active)
        self.assertEqual(q["local_queue_depth"],2)
        self.assertEqual(q["local_queue_prompt_tokens_recent"],300)
        self.assertEqual(q["local_queue_prompt_tok_s"],5.0)
        self.assertIn("spark1:5", q["local_queue_prompt_tok_s_by_node"])
        self.assertEqual(q["local_queue_completion_tokens_recent"],120)
        self.assertEqual(q["local_queue_completion_tok_s"],2.0)
        self.assertIn("spark1:2", q["local_queue_completion_tok_s_by_node"])


if __name__ == "__main__":
    unittest.main()
