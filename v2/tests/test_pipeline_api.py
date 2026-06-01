from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from ds4_infer.api import CoordinatorApi
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import OpenAICompatibleRunner, PipelineOpenAIRunner, _openai_payload
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


class PipelineApiTests(unittest.TestCase):
    def test_pipeline_openai_payload_uses_served_model_name(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "served-name",
                "capability": "smartest",
                "chat": False,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 8,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"text": "ping"},
                "output_contract": {"format": "text"},
            }
        )
        self.assertEqual(_openai_payload(request, profile)["model"], "deepseek-v4-flash-pp8")

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

    def test_pipeline_worker_refills_under_existing_compute_lease(self) -> None:
        class Runner:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def run_one_on_node(self, request, profile, node_id):
                self.calls.append(request.request_id)
                return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=request.request_id, status="completed")

        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            requests = [
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": f"pipe-{idx}",
                    "capability": "efficient",
                    "chat": False,
                    "immediate": False,
                    "job_class": "world_model_extract",
                    "max_output_tokens": 16,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"text": f"event {idx}"},
                    "output_contract": {"format": "text"},
                }
                for idx in range(5)
            ]
            code, payload = api.handle_post("/ds4/queue/submit", {"batch_id": "pipe-refill", "requests": requests})
            self.assertEqual(code, 200)
            self.assertEqual(payload["selected_services"], {"qwen27_bf16_pp8": 5})
            topology = SparkTopology.load(TOPOLOGY)
            runner = Runner()
            worked = api.queue.work(
                registry=ProfileRegistry.load(PROFILES),
                runner=runner,
                node_id="spark0",
                batch_id="pipe-refill",
                limit=2,
                concurrency=2,
                node_profile_ids=tuple(topology.pipeline_profiles),
                kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                batch_limits_by_service={"qwen27_bf16_pp8": 2},
                refill_low_watermarks_by_service={"qwen27_bf16_pp8": 1},
            )
            self.assertEqual(worked["batch_dispatch_mode"], "rolling_refill")
            self.assertEqual(worked["claimed_count"], 5)
            self.assertEqual(worked["completed_count"], 5)
            self.assertEqual(api.queue.status(batch_id="pipe-refill")["state"], "completed")
            self.assertEqual(sorted(runner.calls), [f"pipe-{idx}" for idx in range(5)])

    def test_pipeline_worker_prefers_cohort_batch_over_refill_stream(self) -> None:
        class BatchRunner:
            def __init__(self) -> None:
                self.batches: list[list[str]] = []

            def run_one_on_node(self, request, profile, node_id):
                raise AssertionError("batch-capable pipeline claims must not fall back to per-request dispatch")

            def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
                self.batches.append([request.request_id for request in requests])
                return {request.request_id: make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=request.request_id, status="completed") for request in requests}

        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            requests = [
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": f"cohort-{idx}",
                    "capability": "efficient",
                    "chat": False,
                    "immediate": False,
                    "job_class": "world_model_extract",
                    "max_output_tokens": 16,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"text": f"event {idx}"},
                    "output_contract": {"format": "text"},
                }
                for idx in range(4)
            ]
            api.handle_post("/ds4/queue/submit", {"batch_id": "cohort-batch", "requests": requests})
            topology = SparkTopology.load(TOPOLOGY)
            runner = BatchRunner()
            worked = api.queue.work(
                registry=ProfileRegistry.load(PROFILES),
                runner=runner,
                node_id="spark0",
                batch_id="cohort-batch",
                limit=4,
                concurrency=4,
                node_profile_ids=tuple(topology.pipeline_profiles),
                kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                batch_limits_by_service={"qwen27_bf16_pp8": 4},
                refill_low_watermarks_by_service={"qwen27_bf16_pp8": 1},
            )
            self.assertEqual(worked["batch_dispatch_mode"], "batch")
            self.assertEqual(worked["batch_dispatch_count"], 1)
            self.assertEqual(runner.batches, [[f"cohort-{idx}" for idx in range(4)]])

    def test_pipeline_runner_coalesces_completion_prompts(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        requests = [
            InferenceRequest.from_json(
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": f"prompt-{idx}",
                    "capability": "efficient",
                    "chat": False,
                    "immediate": False,
                    "job_class": "analysis",
                    "max_output_tokens": 8,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"prompt": f"prompt {idx}"},
                    "output_contract": {"format": "text"},
                }
            )
            for idx in range(3)
        ]
        calls: list[dict] = []
        original = OpenAICompatibleRunner._post_json

        def fake_post(self, endpoint, payload):
            calls.append({"endpoint": endpoint, "payload": payload})
            return {
                "choices": [{"index": idx, "text": f"answer {idx}"} for idx in range(3)],
                "usage": {"prompt_tokens": 30, "completion_tokens": 24, "total_tokens": 54},
            }

        try:
            OpenAICompatibleRunner._post_json = fake_post
            runner = PipelineOpenAIRunner(base_urls={"qwen3_6_27b_bf16_pp8_efficient_v1": "http://127.0.0.1:9"})
            results = runner.run_many_on_node(requests, profile, "spark0", concurrency=3)
        finally:
            OpenAICompatibleRunner._post_json = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["endpoint"], "/v1/completions")
        self.assertEqual(calls[0]["payload"]["prompt"], ["prompt 0", "prompt 1", "prompt 2"])
        self.assertEqual([results[f"prompt-{idx}"]["output"]["text"] for idx in range(3)], ["answer 0", "answer 1", "answer 2"])
        self.assertTrue(results["prompt-0"]["transport"]["coalesced_completion_batch"])

    def test_pipeline_runner_prestages_common_strict_kv_prefix(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        prefix = "stable shared prefix " * 80
        plan = {
            "format": "ds4-kv-cache-plan-v1",
            "backend": "simple_cpu_offload",
            "cache_id": "bench-prefix",
            "prefix_hash": "sha256:prefix",
            "load": {"mode": "require", "transport": "local_store"},
            "store": {"mode": "skip", "transport": "none"},
            "miss_policy": "fail",
            "route_affinity": "required",
            "model_fingerprint": {},
            "operation": "load",
            "batch_key_hash": "sha256:batch",
        }
        requests = [
            InferenceRequest.from_json(
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": f"kv-{idx}",
                    "capability": "efficient",
                    "chat": False,
                    "immediate": False,
                    "job_class": "analysis",
                    "max_output_tokens": 8,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"prompt": f"{prefix}request {idx}", "kv_cache_plan": plan},
                    "output_contract": {"format": "text"},
                }
            )
            for idx in range(3)
        ]
        calls: list[dict] = []
        original = OpenAICompatibleRunner._post_json

        def fake_post(self, endpoint, payload):
            calls.append({"endpoint": endpoint, "payload": payload})
            if isinstance(payload.get("prompt"), list):
                return {
                    "choices": [{"index": idx, "text": f"answer {idx}"} for idx in range(3)],
                    "usage": {"prompt_tokens": 30, "completion_tokens": 24, "total_tokens": 54},
                }
            return {"choices": [{"index": 0, "text": "warm"}], "usage": {"completion_tokens": 1}}

        try:
            OpenAICompatibleRunner._post_json = fake_post
            runner = PipelineOpenAIRunner(base_urls={"qwen3_6_27b_bf16_pp8_efficient_v1": "http://127.0.0.1:9"})
            results = runner.run_many_on_node(requests, profile, "spark0", concurrency=3)
        finally:
            OpenAICompatibleRunner._post_json = original
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["payload"]["prompt"], prefix + "request ")
        self.assertEqual(calls[0]["payload"]["extra_body"]["ds4_kv_cache"], plan)
        self.assertEqual(calls[1]["payload"]["prompt"], [f"{prefix}request {idx}" for idx in range(3)])
        self.assertEqual(results["kv-0"]["transport"]["kv_prestage"]["strategy"], "single-prefix-load-before-cohort")


if __name__ == "__main__":
    unittest.main()
