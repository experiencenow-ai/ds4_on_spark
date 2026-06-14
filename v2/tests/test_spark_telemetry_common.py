from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import spark_telemetry_common as telemetry  # noqa: E402


class SparkTelemetryCommonTests(unittest.TestCase):
    def test_resident_targets_filter_stale_pipeline_status(self) -> None:
        queue = {
            "state_counts": {"completed": 1},
            "pipeline_status": {
                "service_id": None,
                "kv_shards": [
                    {"node_id": "spark0", "service_id": "dsv4_flash_pp8", "entries": 2, "bytes": 2},
                ],
                "stages": [
                    {"node_id": "spark0", "service_id": "dsv4_flash_pp8"},
                ],
            },
        }
        dispatcher = {
            "resident_multimodel": True,
            "resident_service_targets": {
                "gemma4_26b_a4b_pp13": 16,
                "kimi27_pp13": 256,
                "qwen27_bf16_pp13": 32,
            },
            "auto_kv_cache_enabled": True,
            "auto_kv_cache_service_ids": [
                "gemma4_26b_a4b_pp13",
                "kimi27_pp13",
                "qwen27_bf16_pp13",
            ],
        }
        out = telemetry.ds4_api_queue_from_status(queue, "test", dispatcher, {}, {})

        self.assertEqual(out["local_queue_active_services"], "gemma4_26b_a4b_pp13,kimi27_pp13,qwen27_bf16_pp13")
        self.assertEqual(out["local_queue_active_service_count"], 3)
        self.assertEqual(out["local_queue_kv_shards"], 0)
        self.assertEqual(out["local_queue_kv_by_node"], "")
        self.assertEqual(out["local_queue_stage_service_by_node"], "")
        self.assertEqual(out["local_queue_kv_services"], "gemma4_26b_a4b_pp13,kimi27_pp13,qwen27_bf16_pp13")

    def test_pipeline_status_remains_fallback_without_resident_targets(self) -> None:
        queue = {
            "state_counts": {"completed": 1},
            "pipeline_status": {
                "service_id": "dsv4_flash_pp8",
                "kv_shards": [
                    {"node_id": "spark0", "service_id": "dsv4_flash_pp8", "entries": 2, "bytes": 2},
                ],
                "stages": [
                    {"node_id": "spark0", "service_id": "dsv4_flash_pp8"},
                ],
            },
        }
        out = telemetry.ds4_api_queue_from_status(queue, "test", {}, {}, {})

        self.assertEqual(out["local_queue_active_services"], "dsv4_flash_pp8")
        self.assertEqual(out["local_queue_kv_shards"], 1)
        self.assertEqual(out["local_queue_kv_by_node"], "spark0:dsv4_flash_pp8")
        self.assertEqual(out["local_queue_stage_service_by_node"], "spark0:dsv4_flash_pp8")


if __name__ == "__main__":
    unittest.main()
