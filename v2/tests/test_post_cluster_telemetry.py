from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_post_cluster_telemetry.py"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge = load_script_module("ds4_post_cluster_telemetry", SCRIPT)


class PostClusterTelemetryTests(unittest.TestCase):
    def test_build_report_maps_cluster_summary_to_pipeline_stages(self) -> None:
        topology = {
            "routing_policy": {
                "pipeline_services": {
                    "svc": {
                        "profile_id": "profile-a",
                        "node_ids": ["spark0", "spark1"],
                        "layer_partition": [3, 2],
                    }
                }
            }
        }
        summary = {
            "updated_unix": 123.5,
            "combined_csv": "/tmp/combined.csv",
            "nodes": {
                "spark0": {"last_gpu_util_pct": 91.0, "sample_count": 5},
                "spark1": {"last_gpu_util_pct": 88.0, "last_vllm_generation_tokens_per_s": 42.0},
            },
        }

        report = bridge.build_report(summary, topology, service_id="svc")

        self.assertEqual(report["format"], "ds4-cluster-telemetry-bridge-v1")
        self.assertEqual([(stage["node_id"], stage["layer_start"], stage["layer_end"]) for stage in report["stages"]], [("spark0", 0, 3), ("spark1", 3, 5)])
        self.assertEqual(report["stages"][0]["payload"]["last_gpu_util_pct"], 91.0)
        self.assertEqual(report["stages"][1]["payload"]["last_vllm_generation_tokens_per_s"], 42.0)


if __name__ == "__main__":
    unittest.main()
