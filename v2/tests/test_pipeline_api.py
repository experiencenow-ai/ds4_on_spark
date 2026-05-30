from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ds4_infer.api import CoordinatorApi
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


class PipelineApiTests(unittest.TestCase):
    def test_submit_binds_to_spark0_pipeline_and_kv_shards_are_layer_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            code, payload = api.handle_post(
                "/ds4/queue/submit",
                {
                    "batch_id": "wm-smoke",
                    "requests": [
                        {
                            "format": "ds4-inference-request-v1",
                            "request_id": "wm-0001",
                            "capability": "efficient",
                            "chat": False,
                            "immediate": False,
                            "job_class": "world_model_extract",
                            "max_output_tokens": 16,
                            "thinking_budget_tokens": 0,
                            "temperature": 0,
                            "input": {"text": "event"},
                            "metadata": {"kv_cache_key": "wm:0001", "kv_bytes_estimate": 8192},
                            "output_contract": {"format": "json", "strict_json": True},
                        }
                    ],
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(payload["selected_nodes"], {"spark0": 1})
            self.assertEqual(payload["selected_services"], {"qwen27_bf16_pp8": 1})

            topology = SparkTopology.load(TOPOLOGY)
            prepared = api.queue.prepare_ready(
                node_id="spark0",
                eligible_profile_ids=tuple(topology.pipeline_profiles),
                batch_id="wm-smoke",
                limit=1,
                leased_by="test",
                lease_ttl_s=30,
                kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
            )
            self.assertEqual(prepared, 1)
            code, status = api.handle_get("/ds4/pipelines", {})
            self.assertEqual(code, 200)
            spark7 = next(shard for shard in status["queue"]["kv_shards"] if shard["service_id"] == "qwen27_bf16_pp8" and shard["node_id"] == "spark7")
            self.assertEqual(spark7["bytes"], 1024)
            self.assertEqual((spark7["layer_start"], spark7["layer_end"]), (59, 64))

    def test_telemetry_report_can_be_stage_shorthand_and_is_completed_from_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            code, result = api.handle_post(
                "/ds4/pipeline/telemetry",
                {
                    "service_id": "dsv4_flash_pp8",
                    "node_id": "spark4",
                    "state": "prod",
                    "metrics": {"decode_tok_s": 4.5},
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(result["stage_index"], 4)
            code, status = api.handle_get("/ds4/pipelines", {})
            self.assertEqual(code, 200)
            stage = status["queue"]["stages"][0]
            self.assertEqual(stage["service_id"], "dsv4_flash_pp8")
            self.assertEqual(stage["node_id"], "spark4")
            self.assertEqual((stage["layer_start"], stage["layer_end"], stage["layer_count"]), (23, 28, 5))


if __name__ == "__main__":
    unittest.main()
