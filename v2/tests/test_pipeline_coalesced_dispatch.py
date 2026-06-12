from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import tempfile
import threading
import time
import unittest

from ds4_infer.api import CoordinatorApi
from ds4_infer.dispatcher_resident import ResidentServicePlan, resident_service_plans
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import OpenAICompatibleRunner
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology
from ds4_infer.worker import BatchWorker


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


def completion_request(request_id: str, prompt: str = "prompt", *, max_output_tokens: int = 32, input_extra: dict | None = None) -> InferenceRequest:
    input_payload = {"prompt": prompt, "openai": {"ignore_eos": True, "min_tokens": max_output_tokens}}
    if input_extra:
        input_payload.update(input_extra)
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": "efficient",
            "chat": False,
            "immediate": False,
            "job_class": "summary",
            "max_output_tokens": max_output_tokens,
            "thinking_budget_tokens": 0,
            "temperature": 0.0,
            "input": input_payload,
            "output_contract": {"format": "text"},
        }
    )


def dsv4_chat_request(request_id: str) -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": "smart",
            "chat": True,
            "immediate": False,
            "job_class": "analysis",
            "max_output_tokens": 64,
            "thinking_budget_tokens": 0,
            "temperature": 0.0,
            "input": {"messages": [{"role": "user", "content": "find the bug"}]},
            "output_contract": {"format": "text"},
            "model_pin": {"profile_id": "dsv4_vllm_mtp_pp8_smartest_v1"},
        }
    )


class RecordingOpenAIRunner(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://test.invalid")
        self.calls: list[tuple[str, dict]] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        self.calls.append((endpoint, payload))
        prompts = payload["prompt"]
        prompt_count = len(prompts) if isinstance(prompts, list) else 1
        return {
            "choices": [{"index": index, "text": f"out-{index}"} for index in range(prompt_count)],
            "usage": {"completion_tokens": prompt_count * int(payload["max_tokens"])},
        }


class FailingLargeCohortOpenAIRunner(RecordingOpenAIRunner):
    def _post_json(self, endpoint: str, payload: dict) -> dict:
        prompts = payload["prompt"]
        if isinstance(prompts, list) and len(prompts) > 2:
            raise RuntimeError("HTTP 413: payload exceeds token budget")
        return super()._post_json(endpoint, payload)


class ConcurrentRecordingOpenAIRunner(RecordingOpenAIRunner):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.02)
            return super()._post_json(endpoint, payload)
        finally:
            with self.lock:
                self.active -= 1


class RecordingBatchRunner:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        self.batch_sizes.append(len(requests))
        return {
            request.request_id: make_result(
                request=request,
                profile_id=profile.profile_id,
                model_id=profile.model_id,
                backend=profile.backend,
                text=f"batched-{request.request_id}",
            )
            for request in requests
        }

    def run_one_on_node(self, request, profile, node_id):
        raise AssertionError("dispatcher should not use per-request run_one_on_node for a compatible cohort")


class PipelineCoalescedDispatchTests(unittest.TestCase):
    def test_runner_sends_one_openai_completion_request_for_compatible_completion_cohort(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = RecordingOpenAIRunner()
        requests = [completion_request(f"r{index}", f"prompt-{index}") for index in range(4)]

        results = runner.run_many_completion(requests, profile)

        self.assertIsNotNone(results)
        assert results is not None
        self.assertEqual(len(runner.calls), 1)
        endpoint, payload = runner.calls[0]
        self.assertEqual(endpoint, "/v1/completions")
        self.assertEqual(payload["prompt"], ["prompt-0", "prompt-1", "prompt-2", "prompt-3"])
        self.assertTrue(payload["ignore_eos"])
        self.assertEqual(payload["min_tokens"], 32)
        self.assertEqual([results[f"r{index}"]["output"]["text"] for index in range(4)], ["out-0", "out-1", "out-2", "out-3"])
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_batch"] for index in range(4)))

    def test_runner_splits_coalesced_completion_requests_by_token_budget(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = RecordingOpenAIRunner()
        requests = [completion_request(f"r{index}", f"prompt-{index}") for index in range(8)]
        old = os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET")
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = "100"
        try:
            results = runner.run_many_completion(requests, profile)
        finally:
            if old is None:
                os.environ.pop("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET", None)
            else:
                os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = old

        self.assertIsNotNone(results)
        self.assertEqual([len(call[1]["prompt"]) for call in runner.calls], [2, 2, 2, 2])
        assert results is not None
        self.assertEqual(len(results), 8)
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_batch"] for index in range(8)))

    def test_runner_uses_explicit_benchmark_token_hint_for_admission(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = RecordingOpenAIRunner()
        prompt = "Request. " + " ".join("benchmark" for _ in range(128))
        input_extra = {"benchmark_shape": {"input_tokens": 128, "output_tokens": 128}}
        requests = [completion_request(f"r{index}", prompt, max_output_tokens=128, input_extra=input_extra) for index in range(32)]
        old_values = {
            "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"),
            "DS4_PIPELINE_COMPLETION_COHORT_MAX": os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_MAX"),
            "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": os.environ.get("DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"),
            "DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS": os.environ.get("DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS"),
        }
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = "16384"
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_MAX"] = "64"
        os.environ["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"] = "64"
        os.environ["DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS"] = "1"
        try:
            results = runner.run_many_completion(requests, profile)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertIsNotNone(results)
        assert results is not None
        self.assertEqual([len(call[1]["prompt"]) for call in runner.calls], [32])
        self.assertEqual(len(results), 32)
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_batch_size"] == 32 for index in range(32)))

    def test_runner_can_budget_cohorts_by_prefill_tokens_only(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = RecordingOpenAIRunner()
        prompt = "Request. " + " ".join("benchmark" for _ in range(128))
        input_extra = {"benchmark_shape": {"input_tokens": 128, "output_tokens": 512}}
        requests = [completion_request(f"r{index}", prompt, max_output_tokens=512, input_extra=input_extra) for index in range(92)]
        old_values = {
            "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"),
            "DS4_PIPELINE_COMPLETION_COHORT_MAX": os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_MAX"),
            "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": os.environ.get("DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"),
            "DS4_PIPELINE_COMPLETION_COHORT_BUDGET_INCLUDE_OUTPUT": os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_BUDGET_INCLUDE_OUTPUT"),
            "DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS": os.environ.get("DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS"),
        }
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = "16384"
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_MAX"] = "128"
        os.environ["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"] = "128"
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_BUDGET_INCLUDE_OUTPUT"] = "0"
        os.environ["DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS"] = "1"
        try:
            results = runner.run_many_completion(requests, profile)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertIsNotNone(results)
        assert results is not None
        self.assertEqual([len(call[1]["prompt"]) for call in runner.calls], [92])
        self.assertEqual(len(results), 92)

    def test_default_coalesced_completion_token_budget_splits_large_cohort(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = RecordingOpenAIRunner()
        prompt = " ".join("benchmark" for _ in range(512))
        requests = [completion_request(f"r{index}", prompt) for index in range(256)]
        old = os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET")
        os.environ.pop("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET", None)
        try:
            results = runner.run_many_completion(requests, profile)
        finally:
            if old is not None:
                os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = old

        self.assertIsNotNone(results)
        sizes = [len(call[1]["prompt"]) for call in runner.calls]
        self.assertEqual(sum(sizes), 256)
        self.assertLess(max(sizes), 256)

    def test_coalesced_completion_bisects_oversized_transport_failure(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = FailingLargeCohortOpenAIRunner()
        requests = [completion_request(f"r{index}", f"prompt-{index}") for index in range(4)]
        old_budget = os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET")
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = "0"
        try:
            results = runner.run_many_completion(requests, profile)
        finally:
            if old_budget is None:
                os.environ.pop("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET", None)
            else:
                os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = old_budget

        self.assertIsNotNone(results)
        assert results is not None
        self.assertEqual([len(call[1]["prompt"]) for call in runner.calls], [2, 2])
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_split_retry"] for index in range(4)))
        self.assertTrue(all(results[f"r{index}"]["transport"]["original_coalesced_batch_size"] == 4 for index in range(4)))

    def test_pipeline_completion_cohort_uses_concurrent_pp_safe_chunks(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = ConcurrentRecordingOpenAIRunner()
        requests = [completion_request(f"r{index}", f"prompt-{index}") for index in range(8)]
        old_values = {
            "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"),
            "DS4_PIPELINE_COMPLETION_COHORT_MAX": os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_MAX"),
            "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": os.environ.get("DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"),
            "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY": os.environ.get("DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"),
        }
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"] = "0"
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_MAX"] = "512"
        os.environ["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"] = "3"
        os.environ["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"] = "4"
        try:
            results = runner.run_many_completion(requests, profile)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertIsNotNone(results)
        assert results is not None
        self.assertEqual(sorted(len(call[1]["prompt"]) for call in runner.calls), [2, 3, 3])
        self.assertGreater(runner.max_active, 1)
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_planned_split"] for index in range(8)))
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_chunk_count"] == 3 for index in range(8)))
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_effective_max_cohort"] == 3 for index in range(8)))
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_chunk_concurrency"] == 4 for index in range(8)))

    def test_background_dispatcher_claims_one_cohort_instead_of_one_future_per_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            api.dispatcher_batch_linger_s = 0.0
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            requests = [completion_request(f"q{index}", f"prompt-{index}") for index in range(8)]
            api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="cohort", priority=10)
            runner = RecordingBatchRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=1.0)
            pending = {}
            with ThreadPoolExecutor(max_workers=4) as executor:
                submitted = api._dispatcher_refill(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"qwen27_bf16_pp8": 64, "dsv4_flash_pp8": 64},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                )
                self.assertEqual(submitted, 8)
                self.assertEqual(len(pending), 1)
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (8, 0, 0))
            self.assertEqual(runner.batch_sizes, [8])

    def test_resident_dispatcher_coalesces_independent_dsv4_app_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=api.dispatcher_batch_linger_s)
            self.assertGreater(plans["dsv4_flash_pp8"].batch_linger_s, 0.0)
            for index in range(3):
                api.queue.submit_requests(
                    requests=[dsv4_chat_request(f"dsv4-agent-{index}")],
                    registry=registry,
                    topology=topology,
                    batch_id=f"agent-{index}",
                    priority=10,
                )
            runner = RecordingBatchRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=1.0)
            pending = {}
            with ThreadPoolExecutor(max_workers=4) as executor:
                submitted = api._dispatcher_refill_resident_multimodel(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"dsv4_flash_pp8": 64},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans=plans,
                )
                self.assertEqual(submitted, 0)
                self.assertEqual(len(pending), 0)
                time.sleep(plans["dsv4_flash_pp8"].batch_linger_s + 0.02)
                submitted = api._dispatcher_refill_resident_multimodel(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"dsv4_flash_pp8": 64},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans=plans,
                )
                self.assertEqual(submitted, 3)
                self.assertEqual(len(pending), 1)
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (3, 0, 0))
            self.assertEqual(runner.batch_sizes, [3])

    def test_resident_refill_waits_for_low_watermark_then_restores_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            plan = ResidentServicePlan(
                service_id="qwen27_bf16_pp12",
                profile_id="qwen27_bf16_pp12",
                compute_domain="qwen27_bf16_pp12",
                target_active=128,
                low_watermark=96,
                max_cohort_size=128,
                batch_linger_s=0.0,
            )
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 127}, 0, 192), 0)
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 96}, 0, 192), 0)
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 95}, 0, 192), 33)
            self.assertEqual(api._resident_refill_limit(plan, {}, 0, 192), 128)

    def test_dispatcher_status_reports_kv_admission_bound(self) -> None:
        old = os.environ.get("DS4_API_DISPATCH_KV_CAPACITY_BYTES")
        os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = "12345"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                status = api.dispatcher_status()
                self.assertEqual(status["kv_capacity_bytes"], 12345)
                self.assertFalse(status["kv_admission_unlimited"])
                self.assertIsNone(status["kv_admission_warning"])
        finally:
            if old is None:
                os.environ.pop("DS4_API_DISPATCH_KV_CAPACITY_BYTES", None)
            else:
                os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = old

    def test_resource_governor_hot_sample_delays_dispatcher_refill(self) -> None:
        old_values = {
            "DS4_API_RESOURCE_GOVERNOR": os.environ.get("DS4_API_RESOURCE_GOVERNOR"),
            "DS4_API_RESOURCE_SAMPLE_JSON": os.environ.get("DS4_API_RESOURCE_SAMPLE_JSON"),
            "DS4_API_RESOURCE_TEMP_SOFT_C": os.environ.get("DS4_API_RESOURCE_TEMP_SOFT_C"),
            "DS4_API_RESOURCE_TEMP_HARD_C": os.environ.get("DS4_API_RESOURCE_TEMP_HARD_C"),
            "DS4_API_RESOURCE_THROTTLE_STEP_S": os.environ.get("DS4_API_RESOURCE_THROTTLE_STEP_S"),
        }
        os.environ["DS4_API_RESOURCE_GOVERNOR"] = "1"
        os.environ["DS4_API_RESOURCE_SAMPLE_JSON"] = json.dumps({"nodes": {"spark0": {"temperature_c": 91, "power_w": 95, "utilization_pct": 96}}})
        os.environ["DS4_API_RESOURCE_TEMP_SOFT_C"] = "86"
        os.environ["DS4_API_RESOURCE_TEMP_HARD_C"] = "88"
        os.environ["DS4_API_RESOURCE_THROTTLE_STEP_S"] = "0.1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                registry = ProfileRegistry.load(PROFILES)
                topology = SparkTopology.load(TOPOLOGY)
                requests = [completion_request("hot0")]
                api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="hot", priority=10)
                worker = BatchWorker(queue=api.queue, registry=registry, runner=RecordingBatchRunner(), worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=1.0)
                pending = {}
                with ThreadPoolExecutor(max_workers=1) as executor:
                    submitted = api._dispatcher_refill(
                        worker=worker,
                        executor=executor,
                        pending=pending,
                        entry_node_id="spark0",
                        node_profile_ids=tuple(topology.pipeline_profiles),
                        batch_limits_by_service={"qwen27_bf16_pp8": 64, "dsv4_flash_pp8": 64},
                        kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    )
                status = api.dispatcher_status()
                self.assertEqual(submitted, 0)
                self.assertEqual(len(pending), 0)
                self.assertTrue(status["resource_governor"]["throttle_active"])
                self.assertIn("temp_hard", status["resource_governor"]["throttle_reasons"])
                self.assertEqual(status["resource_governor_throttle_count"], 1)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_completion_prompt_array_is_submitted_as_one_ds4_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            code, payload = api.handle_post(
                "/v1/completions",
                {
                    "model": "qwen27_bf16_pp8",
                    "prompt": ["a", "b", "c"],
                    "max_tokens": 8,
                    "temperature": 0.0,
                    "batch_id": "prompt-array",
                    "extra_body": {"ignore_eos": True, "min_tokens": 8},
                },
            )
        self.assertEqual(code, 200)
        self.assertEqual(len(payload["choices"]), 3)
        self.assertEqual([choice["index"] for choice in payload["choices"]], [0, 1, 2])
        self.assertEqual(payload["ds4"]["result_count"], 3)

    def test_dispatcher_batch_limit_can_be_overridden_without_editing_topology(self) -> None:
        from ds4_infer.api import _batch_limits_by_service

        old = os.environ.get("DS4_API_BATCH_LIMITS_JSON")
        os.environ["DS4_API_BATCH_LIMITS_JSON"] = '{"qwen27_bf16_pp8": 256}'
        try:
            topology = SparkTopology.load(TOPOLOGY)
            limits = _batch_limits_by_service(topology)
        finally:
            if old is None:
                os.environ.pop("DS4_API_BATCH_LIMITS_JSON", None)
            else:
                os.environ["DS4_API_BATCH_LIMITS_JSON"] = old
        self.assertEqual(limits["qwen27_bf16_pp8"], 256)


if __name__ == "__main__":
    unittest.main()
