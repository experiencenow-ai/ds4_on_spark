from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from ds4_infer import api as api_module
from ds4_infer.api import CoordinatorApi
from ds4_infer.api_stream import _drain_completion_stream_events, openai_completion_stream_events
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import OpenAICompatibleRunner, PipelineOpenAIRunner, _openai_payload
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


class PipelineApiTests(unittest.TestCase):
    def test_default_sync_timeout_is_benchmark_safe(self) -> None:
        original = os.environ.pop("DS4_API_SYNC_TIMEOUT_S", None)
        try:
            self.assertGreaterEqual(api_module._default_sync_timeout_s(), 3600.0)
        finally:
            if original is not None:
                os.environ["DS4_API_SYNC_TIMEOUT_S"] = original

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

    def test_pipeline_served_model_override_can_key_by_service_id(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "served-name-pp7",
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
        old = os.environ.get("DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON")
        os.environ["DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON"] = '{"dsv4_flash_pp8":"deepseek-v4-flash-pp7"}'
        try:
            payload = _openai_payload(request, profile)
        finally:
            if old is None:
                os.environ.pop("DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON", None)
            else:
                os.environ["DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON"] = old
        self.assertEqual(payload["model"], "deepseek-v4-flash-pp7")

    def test_pipeline_node_override_rewrites_served_model_pp_suffix(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "served-name-pp7",
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
        old_nodes = os.environ.get("DS4_PIPELINE_NODES")
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX")
        os.environ["DS4_PIPELINE_NODES"] = "spark0,spark1,spark2,spark3,spark4,spark5,spark6"
        os.environ.pop("DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX", None)
        try:
            payload = _openai_payload(request, profile)
        finally:
            if old_nodes is None:
                os.environ.pop("DS4_PIPELINE_NODES", None)
            else:
                os.environ["DS4_PIPELINE_NODES"] = old_nodes
            if old_auto is None:
                os.environ.pop("DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX"] = old_auto
        self.assertEqual(payload["model"], "deepseek-v4-flash-pp7")

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
            self.assertEqual((stage["layer_start"], stage["layer_end"], stage["layer_count"]), (32, 40, 8))

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

    def test_openai_completion_stream_emits_completed_choices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            events = list(
                openai_completion_stream_events(
                    api,
                    {
                        "model": "qwen27_bf16_pp8",
                        "prompt": ["alpha", "beta"],
                        "max_tokens": 7,
                        "stream": True,
                        "ignore_eos": True,
                        "min_tokens": 7,
                    }
                )
            )
        choice_events = [event for event in events if event["choices"]]
        self.assertEqual([event["choices"][0]["index"] for event in choice_events], [0, 1])
        self.assertEqual([event["choices"][0]["finish_reason"] for event in choice_events], ["stop", "stop"])
        self.assertEqual(events[-1]["choices"], [])
        self.assertEqual(events[-1]["ds4"]["result_count"], 2)

    def test_openai_completion_stream_forwards_delta_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            request = InferenceRequest.from_json(
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": "stream-delta",
                    "chat": False,
                    "immediate": False,
                    "job_class": "analysis",
                    "max_output_tokens": 8,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"prompt": "delta"},
                    "output_contract": {"format": "text"},
                }
            )
            api.queue.stream_delta(request_id="stream-delta", text="tok")
            streamed: set[str] = set()
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            _after, chunks = _drain_completion_stream_events(api, "cmpl", "model", "batch", {"stream-delta": (0, request)}, streamed, usage, 0)
        self.assertEqual(chunks[0]["choices"][0]["text"], "tok")
        self.assertIsNone(chunks[0]["choices"][0]["finish_reason"])
        self.assertEqual(chunks[0]["ds4"]["event_type"], "delta")
        self.assertEqual(streamed, {"stream-delta"})

    def test_openai_api_preserves_thinking_budget_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            api.handle_post(
                "/v1/chat/completions",
                {
                    "model": "qwen27_bf16_pp8",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 8,
                    "thinking_budget_tokens": 123,
                    "ds4_async": True,
                    "batch_id": "thinking-chat",
                },
            )
            with api.queue._connect() as conn:
                row = conn.execute("select request_json from requests where batch_id=?", ("thinking-chat",)).fetchone()
            request_json = json.loads(str(row["request_json"]))
        self.assertEqual(request_json["thinking_budget_tokens"], 123)

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
