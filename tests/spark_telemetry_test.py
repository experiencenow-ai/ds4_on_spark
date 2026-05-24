import unittest

from scripts import spark_node_telemetry_monitor as node_mon
from scripts import spark_telemetry_collect as collect


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


if __name__ == "__main__":
    unittest.main()
