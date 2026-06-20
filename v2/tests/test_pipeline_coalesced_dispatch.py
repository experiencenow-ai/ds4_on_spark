from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import unittest.mock

from ds4_infer.api import CoordinatorApi, DispatcherRuntime, _parse_vllm_metrics_snapshot
from ds4_infer.dispatcher_resident import PendingDispatcherCohort, ResidentServicePlan, resident_service_plans
from ds4_infer.dispatcher_resident import pending_cohort_count_by_compute_domain, pending_cohort_count_by_service
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import QueueClaim
from ds4_infer.resource_governor import GpuResourceGovernor, _parse_free_m
from ds4_infer.runners import OpenAICompatibleRunner
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology
from ds4_infer.worker import BatchWorker


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
GLM52_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_glm52_pp13.json"


def completion_request(request_id: str, prompt: str = "prompt", *, max_output_tokens: int = 32, input_extra: dict | None = None, profile_id: str | None = None) -> InferenceRequest:
    input_payload = {"prompt": prompt, "openai": {"ignore_eos": True, "min_tokens": max_output_tokens}}
    if input_extra:
        input_payload.update(input_extra)
    payload = {
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
    if profile_id:
        payload["model_pin"] = {"profile_id": profile_id}
    return InferenceRequest.from_json(payload)


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


class BlockingIncrementalBatchRunner:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.cancel_seen = threading.Event()
        self.release = threading.Event()

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        raise AssertionError("test requires incremental batch path")

    def run_many_on_node_incremental(self, requests, profile, node_id, *, concurrency=1, on_result, on_delta=None, cancel_event=None):
        self.started.set()
        while cancel_event is None or not cancel_event.is_set():
            time.sleep(0.005)
        self.cancel_seen.set()
        self.release.wait(5.0)
        return {}


class BlockingRefillIncrementalRunner:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.batch_sizes: list[int] = []
        self.cancel_seen = threading.Event()

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        raise AssertionError("test requires forced refill stream path")

    def run_many_on_node_incremental(self, requests, profile, node_id, *, concurrency=1, on_result, on_delta=None, cancel_event=None):
        with self.condition:
            self.batch_sizes.append(len(requests))
            self.condition.notify_all()
        while cancel_event is None or not cancel_event.is_set():
            time.sleep(0.005)
        self.cancel_seen.set()
        return {}

    def run_one_on_node(self, request, profile, node_id):
        raise AssertionError("rolling refill should use incremental singleton transport when cancelable")

    def wait_started(self, count: int, timeout_s: float = 1.0) -> bool:
        deadline = time.time() + timeout_s
        with self.condition:
            while len(self.batch_sizes) < count:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return True


class RecordingIncrementalBatchRunner:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        raise AssertionError("test requires incremental batch path")

    def run_many_on_node_incremental(self, requests, profile, node_id, *, concurrency=1, on_result, on_delta=None, cancel_event=None):
        self.batch_sizes.append(len(requests))
        out = {}
        for request in requests:
            result = make_result(
                request=request,
                profile_id=profile.profile_id,
                model_id=profile.model_id,
                backend=profile.backend,
                text=f"incremental-{request.request_id}",
            )
            out[request.request_id] = result
            on_result(request.request_id, result)
        return out

    def run_one_on_node(self, request, profile, node_id):
        raise AssertionError("rolling resident dispatch should batch compatible claims")


class RecordingHybridRunner:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []
        self.calls: list[str] = []

    def run_many_on_node(self, requests, profile, node_id, *, concurrency=1):
        raise AssertionError("test requires incremental batch path")

    def run_many_on_node_incremental(self, requests, profile, node_id, *, concurrency=1, on_result, on_delta=None, cancel_event=None):
        self.batch_sizes.append(len(requests))
        out = {}
        for request in requests:
            result = make_result(
                request=request,
                profile_id=profile.profile_id,
                model_id=profile.model_id,
                backend=profile.backend,
                text=f"incremental-{request.request_id}",
            )
            out[request.request_id] = result
            on_result(request.request_id, result)
        return out

    def run_one_on_node(self, request, profile, node_id):
        self.calls.append(request.request_id)
        return make_result(
            request=request,
            profile_id=profile.profile_id,
            model_id=profile.model_id,
            backend=profile.backend,
            text=f"single-{request.request_id}",
        )


class RecordingPerRequestRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_one_on_node(self, request, profile, node_id):
        self.calls.append(request.request_id)
        return make_result(
            request=request,
            profile_id=profile.profile_id,
            model_id=profile.model_id,
            backend=profile.backend,
            text=f"single-{request.request_id}",
        )


class CancellingPerRequestRunner(RecordingPerRequestRunner):
    def __init__(self, cancel_once) -> None:
        super().__init__()
        self.cancel_once = cancel_once
        self.cancelled = False
        self.lock = threading.Lock()

    def run_one_on_node(self, request, profile, node_id):
        with self.lock:
            if not self.cancelled:
                self.cancelled = True
                self.cancel_once()
        time.sleep(0.01)
        return super().run_one_on_node(request, profile, node_id)


class BlockingPerRequestRunner(RecordingPerRequestRunner):
    def __init__(self) -> None:
        super().__init__()
        self.condition = threading.Condition()
        self.release = threading.Event()

    def run_one_on_node(self, request, profile, node_id):
        with self.condition:
            self.calls.append(request.request_id)
            self.condition.notify_all()
        self.release.wait(5.0)
        return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=f"single-{request.request_id}")

    def wait_started(self, count: int, timeout_s: float = 1.0) -> bool:
        deadline = time.time() + timeout_s
        with self.condition:
            while len(self.calls) < count:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return True


class PipelineCoalescedDispatchTests(unittest.TestCase):
    def test_glm52_resident_plan_uses_scheduler_token_limit(self) -> None:
        topology = SparkTopology.load(GLM52_TOPOLOGY)
        plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
        self.assertEqual(plans["glm52_fp8_pp13"].target_active, 80)
        self.assertEqual(plans["glm52_fp8_pp13"].max_cohort_size, 80)
        self.assertEqual(plans["glm52_fp8_pp13"].max_cohort_tokens, 32768)
        self.assertEqual(plans["glm52_fp8_pp13"].admission_mode, "rolling_refill")

    def test_glm52_dispatcher_status_reports_idle_token_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=GLM52_TOPOLOGY, runner_kind="fake")
            self.assertEqual(api.dispatcher_status()["resident_service_token_limits"], {"glm52_fp8_pp13": 32768})
            self.assertTrue(api.dispatcher_status()["resident_prefer_cohort_batch"])

    def test_host_memory_trim_remediation_allows_dispatcher_refill(self) -> None:
        old_values = {
            "DS4_API_RESOURCE_GOVERNOR": os.environ.get("DS4_API_RESOURCE_GOVERNOR"),
            "DS4_API_RESOURCE_SAMPLE_JSON": os.environ.get("DS4_API_RESOURCE_SAMPLE_JSON"),
            "DS4_API_RESOURCE_HOST_MEMORY_SOFT_PCT": os.environ.get("DS4_API_RESOURCE_HOST_MEMORY_SOFT_PCT"),
            "DS4_API_RESOURCE_HOST_MEMORY_HARD_PCT": os.environ.get("DS4_API_RESOURCE_HOST_MEMORY_HARD_PCT"),
            "DS4_API_RESOURCE_THROTTLE_STEP_S": os.environ.get("DS4_API_RESOURCE_THROTTLE_STEP_S"),
            "DS4_API_TRIM_MEMORY_COOLDOWN_S": os.environ.get("DS4_API_TRIM_MEMORY_COOLDOWN_S"),
            "DS4_API_RESIDENT_PREFER_COHORT_BATCH": os.environ.get("DS4_API_RESIDENT_PREFER_COHORT_BATCH"),
        }
        os.environ["DS4_API_RESOURCE_GOVERNOR"] = "1"
        os.environ["DS4_API_RESOURCE_SAMPLE_JSON"] = json.dumps({"nodes": {"spark0": {"temperature_c": 55, "power_w": 95, "utilization_pct": 72, "host_memory_used_mib": 96, "host_memory_total_mib": 100}}})
        os.environ["DS4_API_RESOURCE_HOST_MEMORY_SOFT_PCT"] = "90"
        os.environ["DS4_API_RESOURCE_HOST_MEMORY_HARD_PCT"] = "95"
        os.environ["DS4_API_RESOURCE_THROTTLE_STEP_S"] = "0.1"
        os.environ["DS4_API_TRIM_MEMORY_COOLDOWN_S"] = "0"
        os.environ.pop("DS4_API_RESIDENT_PREFER_COHORT_BATCH", None)

        trim_calls: list[dict] = []

        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=GLM52_TOPOLOGY, runner_kind="fake")
                registry = ProfileRegistry.load(PROFILES)
                topology = SparkTopology.load(GLM52_TOPOLOGY)
                requests = [completion_request("memtrim0", profile_id="glm52_fp8_pp13_frontier_v1")]
                api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="memtrim", priority=10)
                worker = BatchWorker(queue=api.queue, registry=registry, runner=RecordingIncrementalBatchRunner(), worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=1.0)
                pending = {}
                plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
                plans["glm52_fp8_pp13"].batch_linger_s = 0.0

                def fake_trim(**kwargs):
                    trim_calls.append(kwargs)
                    api.dispatcher_resource_governor.sample_json = json.dumps({"nodes": {"spark0": {"temperature_c": 55, "power_w": 95, "utilization_pct": 72, "host_memory_used_mib": 50, "host_memory_total_mib": 100}}})
                    return ({"attempted": True, "ok": True, "mode": "wait", "services": [{"service_id": "glm52_fp8_pp13", "ok": True}]}, 123.0)

                with unittest.mock.patch("ds4_infer.api.try_trim_host_memory", side_effect=fake_trim):
                    with ThreadPoolExecutor(max_workers=1) as executor:
                        submitted = api._dispatcher_refill(
                            worker=worker,
                            executor=executor,
                            pending=pending,
                            entry_node_id="spark0",
                            node_profile_ids=tuple(topology.pipeline_profiles),
                            batch_limits_by_service={"glm52_fp8_pp13": 80},
                            batch_token_limits_by_service={"glm52_fp8_pp13": 32768},
                            kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                            service_plans=plans,
                        )
                status = api.dispatcher_status()
                self.assertEqual(submitted, 1)
                self.assertEqual(len(trim_calls), 1)
                self.assertEqual(status["host_memory_trim_count"], 1)
                self.assertTrue(status["last_host_memory_trim"]["ok"])
                self.assertFalse(status["resource_governor"]["throttle_active"])
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

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

    def test_auto_kv_does_not_prevent_coalesced_completion_batches_by_default(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = RecordingOpenAIRunner()
        requests = [completion_request(f"r{index}", f"prompt-{index}") for index in range(4)]
        old_values = {
            "DS4_PIPELINE_AUTO_KV_CACHE": os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE"),
            "DS4_PIPELINE_AUTO_KV_BATCH_POLICY": os.environ.get("DS4_PIPELINE_AUTO_KV_BATCH_POLICY"),
            "DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS": os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"),
        }
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"] = "prefer_batch"
        os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
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
        self.assertEqual(len(runner.calls), 1)
        _, payload = runner.calls[0]
        self.assertEqual(payload["prompt"], ["prompt-0", "prompt-1", "prompt-2", "prompt-3"])
        self.assertNotIn("kv_transfer_params", payload)
        self.assertNotIn("ds4_kv_cache", payload.get("extra_body") or {})
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_batch"] for index in range(4)))
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_auto_kv_suppressed"] for index in range(4)))

    def test_auto_kv_strict_cache_policy_keeps_distinct_cache_refs_unbatched(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        runner = RecordingOpenAIRunner()
        requests = [completion_request(f"r{index}", f"prompt-{index}") for index in range(2)]
        old_values = {
            "DS4_PIPELINE_AUTO_KV_CACHE": os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE"),
            "DS4_PIPELINE_AUTO_KV_BATCH_POLICY": os.environ.get("DS4_PIPELINE_AUTO_KV_BATCH_POLICY"),
            "DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS": os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"),
        }
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"] = "strict_cache"
        os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
        try:
            results = runner.run_many_completion(requests, profile)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertIsNone(results)
        self.assertEqual(runner.calls, [])

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
        self.assertTrue(all(results[f"r{index}"]["transport"]["coalesced_completion_split_retry_reason"] == "HTTP 413: payload exceeds token budget" for index in range(4)))

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

    def test_resident_service_admission_mode_can_be_overridden_by_env(self) -> None:
        old_json = os.environ.get("DS4_API_SERVICE_ADMISSION_MODES_JSON")
        old_default = os.environ.get("DS4_API_SERVICE_ADMISSION_MODE")
        try:
            os.environ["DS4_API_SERVICE_ADMISSION_MODES_JSON"] = json.dumps({"dsv4_flash_pp8": "resident_multimodel_rolling_refill"})
            os.environ.pop("DS4_API_SERVICE_ADMISSION_MODE", None)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            self.assertEqual(plans["dsv4_flash_pp8"].admission_mode, "resident_multimodel_rolling_refill")
            os.environ["DS4_API_SERVICE_ADMISSION_MODES_JSON"] = json.dumps({"dsv4_vllm_mtp_pp8_smartest_v1": "rolling_refill"})
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            self.assertEqual(plans["dsv4_flash_pp8"].admission_mode, "rolling_refill")
            os.environ.pop("DS4_API_SERVICE_ADMISSION_MODES_JSON", None)
            os.environ["DS4_API_SERVICE_ADMISSION_MODE"] = "resident_multimodel_rolling_refill"
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            self.assertEqual(plans["qwen27_bf16_pp8"].admission_mode, "resident_multimodel_rolling_refill")
        finally:
            if old_json is None:
                os.environ.pop("DS4_API_SERVICE_ADMISSION_MODES_JSON", None)
            else:
                os.environ["DS4_API_SERVICE_ADMISSION_MODES_JSON"] = old_json
            if old_default is None:
                os.environ.pop("DS4_API_SERVICE_ADMISSION_MODE", None)
            else:
                os.environ["DS4_API_SERVICE_ADMISSION_MODE"] = old_default

    def test_resident_refill_waits_for_low_watermark_then_overlaps_next_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            plan = ResidentServicePlan(
                service_id="qwen27_bf16_pp12",
                profile_id="qwen27_bf16_pp12",
                compute_domain="qwen27_bf16_pp12",
                target_active=128,
                queue_depth_target=128,
                low_watermark=96,
                max_cohort_size=128,
                max_cohort_tokens=0,
                batch_linger_s=0.0,
            )
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 127}, 0, 192), 0)
            plan.admission_mode = "resident_multimodel_rolling_refill"
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 96}, 0, 192), 128)
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 95}, 0, 192), 128)
            self.assertEqual(api._resident_refill_limit(plan, {}, 0, 192), 128)
            api.dispatcher_refill_batch = 256
            plan.queue_depth_target = 256
            plan.low_watermark = 192
            plan.max_cohort_size = 256
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 193}, 0, 256), 0)
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 192}, 0, 256), 256)
            self.assertEqual(api._resident_refill_limit(plan, {"qwen27_bf16_pp12": 128}, 0, 256), 256)
            self.assertEqual(api._resident_refill_limit(plan, {}, 0, 256), 256)

    def test_rolling_cohort_reports_partial_completion_for_refill(self) -> None:
        claims = [
            QueueClaim(
                request_id=f"r{index}",
                batch_id="batch",
                request_kind="model",
                selected_profile_id="profile",
                selected_node_id="spark0",
                lease_id=f"lease-{index}",
                attempt_count=1,
                request=None,
                selected_service_id="svc",
                selected_compute_domain="fleet",
            )
            for index in range(2)
        ]
        cohort = PendingDispatcherCohort.from_claims(claims, admission_mode="rolling_refill")
        self.assertEqual(cohort.active_count(), 2)
        cohort.mark_finished("r0")
        self.assertEqual(cohort.active_count(), 1)
        self.assertEqual(cohort.status()["initial_unfinished_count"], 1)
        self.assertEqual(cohort.status()["active_count"], 1)
        cohort.mark_finished("r1")
        self.assertEqual(cohort.active_count(), 0)
        self.assertEqual(cohort.status()["initial_unfinished_count"], 0)
        self.assertEqual(cohort.status()["active_count"], 0)

    def test_rolling_cohort_remains_active_batch_after_initial_claims_finish(self) -> None:
        claims = [
            QueueClaim(
                request_id=f"r{index}",
                batch_id="batch",
                request_kind="model",
                selected_profile_id="profile",
                selected_node_id="spark0",
                lease_id=f"lease-{index}",
                attempt_count=1,
                request=None,
                selected_service_id="svc",
                selected_compute_domain="fleet",
            )
            for index in range(2)
        ]
        cohort = PendingDispatcherCohort.from_claims(claims, admission_mode="rolling_refill")
        for claim in claims:
            cohort.mark_finished(claim.request_id)

        self.assertEqual(cohort.active_count(), 0)
        self.assertTrue(cohort.batch_active())
        self.assertTrue(cohort.status()["batch_active"])
        self.assertEqual(pending_cohort_count_by_compute_domain({object(): cohort}), {"fleet": 1})
        self.assertEqual(pending_cohort_count_by_service({object(): cohort}), {"svc": 1})

        normal = PendingDispatcherCohort.from_claims(claims, admission_mode="cohort")
        for claim in claims:
            normal.mark_finished(claim.request_id)
        self.assertFalse(normal.batch_active())
        self.assertEqual(pending_cohort_count_by_compute_domain({object(): normal}), {})
        self.assertEqual(pending_cohort_count_by_service({object(): normal}), {})

    def test_worker_force_cancel_terminal_cancels_incremental_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            requests = [completion_request(f"q{index}", f"prompt-{index}") for index in range(2)]
            api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="cancel-tail", priority=10)
            runner = BlockingIncrementalBatchRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
            notices: list[str] = []
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    worker.run_once,
                    node_id="spark0",
                    batch_id="cancel-tail",
                    limit=2,
                    concurrency=2,
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    on_result=lambda claim, _result: notices.append(claim.request_id),
                )
                try:
                    self.assertTrue(runner.started.wait(1.0))
                    api.queue.cancel(batch_id="cancel-tail", reason="operator cancel", force_running=True)
                    self.assertTrue(runner.cancel_seen.wait(1.0))
                    self.assertEqual(api.queue.status(request_id="q0")["state"], "cancelled")
                    self.assertFalse(api.queue.status(request_id="q0")["cancel_requested"])
                    self.assertEqual(api.queue.status(request_id="q1")["state"], "cancelled")
                    self.assertFalse(api.queue.status(request_id="q1")["cancel_requested"])
                    runner.release.set()
                    summary = future.result(timeout=1.0)
                finally:
                    runner.release.set()
            self.assertEqual(summary["claimed_count"], 2)
            self.assertEqual(summary["completed_count"], 0)
            self.assertEqual(summary["failed_count"], 0)
            self.assertEqual(api.queue.status(batch_id="cancel-tail")["state"], "cancelled")
            self.assertEqual(api.queue.status(request_id="q0")["state"], "cancelled")
            self.assertEqual(api.queue.status(request_id="q1")["state"], "cancelled")
            self.assertEqual(notices, [])

    def test_resident_rolling_admission_refills_until_service_queue_drains(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            plan = plans["dsv4_flash_pp8"]
            plan.admission_mode = "resident_multimodel_rolling_refill"
            plan.target_active = 2
            plan.low_watermark = 1
            plan.max_cohort_size = 2
            plan.batch_linger_s = 0.0
            for index in range(5):
                api.queue.submit_requests(
                    requests=[dsv4_chat_request(f"dsv4-roll-{index}")],
                    registry=registry,
                    topology=topology,
                    batch_id=f"roll-{index}",
                    priority=10,
                )
            runner = RecordingPerRequestRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
            pending = {}
            with ThreadPoolExecutor(max_workers=1) as executor:
                submitted = api._dispatcher_refill_resident_multimodel(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"dsv4_flash_pp8": 2},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans={"dsv4_flash_pp8": plan},
                )
                self.assertEqual(submitted, 2)
                self.assertEqual(len(pending), 1)
                details = api.dispatcher_status()["pending_cohort_details"]
                self.assertEqual(details[0]["admission_mode"], "rolling_refill")
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (5, 0, 0))
            self.assertEqual(api.queue.status(batch_id="roll-4")["state"], "completed")
            self.assertEqual(sorted(runner.calls), [f"dsv4-roll-{index}" for index in range(5)])
            self.assertEqual(api.dispatcher_status()["last_summary"]["dispatch_mode"], "rolling_refill")
            self.assertEqual(api.dispatcher_status()["last_summary"]["claimed"], 5)

    def test_resident_submit_passes_token_reserve_to_rolling_refill(self) -> None:
        class CapturingCoordinatorApi(CoordinatorApi):
            def __init__(self, *args, **kwargs) -> None:
                super().__init__(*args, **kwargs)
                self.captured_submit: dict | None = None

            def _dispatcher_submit_cohort(self, **kwargs) -> None:
                self.captured_submit = kwargs

        with tempfile.TemporaryDirectory() as tmp:
            api = CapturingCoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            plan = ResidentServicePlan(
                service_id="glm52_fp8_pp13",
                profile_id="glm52_fp8_pp13_frontier_v1",
                compute_domain="spark-ring",
                target_active=80,
                queue_depth_target=80,
                low_watermark=64,
                max_cohort_size=80,
                max_cohort_tokens=32768,
                batch_linger_s=0.0,
                decode_token_reserve=32,
                admission_mode="bounded_cohort_refill",
            )
            claim = QueueClaim(
                request_id="glm-refill",
                batch_id="glm-refill",
                request_kind="model",
                selected_profile_id="glm52_fp8_pp13_frontier_v1",
                selected_node_id="spark0",
                lease_id="lease",
                attempt_count=1,
                request=dsv4_chat_request("glm-refill"),
                selected_service_id="glm52_fp8_pp13",
            )
            worker = BatchWorker(queue=api.queue, registry=ProfileRegistry.load(PROFILES), runner=RecordingPerRequestRunner(), worker_id="test-dispatcher")
            with ThreadPoolExecutor(max_workers=1) as executor:
                submitted = api._resident_submit_claims(
                    executor=executor,
                    worker=worker,
                    pending={},
                    claims=[claim],
                    plan=plan,
                    entry_node_id="spark0",
                    node_profile_ids=("glm52_fp8_pp13_frontier_v1",),
                    batch_limits_by_service={"glm52_fp8_pp13": 80},
                    batch_token_limits_by_service={"glm52_fp8_pp13": 1, "other": 7},
                    kv_shard_layouts_by_profile={},
                )
            self.assertEqual(submitted, 1)
            self.assertIsNotNone(api.captured_submit)
            assert api.captured_submit is not None
            self.assertEqual(api.captured_submit["batch_token_limits_by_service"]["glm52_fp8_pp13"], 32768)
            self.assertEqual(api.captured_submit["batch_token_limits_by_service"]["other"], 7)
            self.assertEqual(api.captured_submit["batch_decode_token_reserves_by_service"], {"glm52_fp8_pp13": 32})

    def test_dispatcher_tick_refreshes_pending_by_service_after_partial_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            worker = BatchWorker(queue=api.queue, registry=registry, runner=RecordingPerRequestRunner(), worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=1.0)
            claims = [
                QueueClaim(
                    request_id=f"active-{index}",
                    batch_id="status",
                    request_kind="model",
                    selected_profile_id="dsv4_vllm_mtp_pp8_smartest_v1",
                    selected_node_id="spark0",
                    lease_id=f"lease-{index}",
                    attempt_count=1,
                    request=dsv4_chat_request(f"active-{index}"),
                    selected_service_id="dsv4_flash_pp8",
                    selected_compute_domain="spark-fleet-0",
                )
                for index in range(3)
            ]
            cohort = PendingDispatcherCohort.from_claims(claims, admission_mode="rolling_refill")
            cohort.mark_finished("active-0")
            release = threading.Event()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(release.wait, 5.0)
                runtime = DispatcherRuntime(
                    worker=worker,
                    executor=executor,
                    pending={future: cohort},
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"dsv4_flash_pp8": 3},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans={},
                    next_heartbeat_at=time.time() + 100.0,
                    last_credit_at=time.time(),
                )
                try:
                    self.assertFalse(api._dispatcher_tick(runtime))
                    self.assertEqual(api.dispatcher_status()["pending"], 2)
                    self.assertEqual(api.dispatcher_status()["pending_by_service"], {"dsv4_flash_pp8": 2})
                finally:
                    release.set()

    def test_resident_rolling_admission_defaults_to_refill_stream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            plan = plans["dsv4_flash_pp8"]
            plan.admission_mode = "resident_multimodel_rolling_refill"
            plan.target_active = 4
            plan.queue_depth_target = 4
            plan.low_watermark = 2
            plan.max_cohort_size = 4
            plan.batch_linger_s = 0.0
            requests = [dsv4_chat_request(f"dsv4-batch-roll-{index}") for index in range(4)]
            api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="roll-batch", priority=10)
            runner = RecordingIncrementalBatchRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
            pending = {}
            with ThreadPoolExecutor(max_workers=1) as executor:
                submitted = api._dispatcher_refill_resident_multimodel(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"dsv4_flash_pp8": 4},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans={"dsv4_flash_pp8": plan},
                )
                self.assertEqual(submitted, 4)
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (4, 0, 0))
            self.assertEqual(runner.batch_sizes, [1, 1, 1, 1])
            status = api.dispatcher_status()
            self.assertEqual(status["last_summary"]["dispatch_mode"], "rolling_refill")
            self.assertEqual(status["last_summary"]["transport_mode"], "rolling_refill_stream")
            self.assertEqual(status["last_summary"]["batch_ineligible_reason"], "rolling_admission_stream")
            self.assertEqual(status["resident_rolling_batch_count"], 0)
            self.assertEqual(status["resident_rolling_refill_stream_count"], 1)

    def test_resident_rolling_admission_can_opt_into_incremental_batch_runner(self) -> None:
        old = os.environ.get("DS4_API_RESIDENT_PREFER_COHORT_BATCH")
        os.environ["DS4_API_RESIDENT_PREFER_COHORT_BATCH"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                registry = ProfileRegistry.load(PROFILES)
                topology = SparkTopology.load(TOPOLOGY)
                plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
                plan = plans["dsv4_flash_pp8"]
                plan.admission_mode = "resident_multimodel_rolling_refill"
                plan.target_active = 4
                plan.queue_depth_target = 4
                plan.low_watermark = 2
                plan.max_cohort_size = 4
                plan.batch_linger_s = 0.0
                requests = [dsv4_chat_request(f"dsv4-batch-roll-{index}") for index in range(4)]
                api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="roll-batch", priority=10)
                runner = RecordingIncrementalBatchRunner()
                worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
                pending = {}
                with ThreadPoolExecutor(max_workers=1) as executor:
                    submitted = api._dispatcher_refill_resident_multimodel(
                        worker=worker,
                        executor=executor,
                        pending=pending,
                        entry_node_id="spark0",
                        node_profile_ids=tuple(topology.pipeline_profiles),
                        batch_limits_by_service={"dsv4_flash_pp8": 4},
                        kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                        service_plans={"dsv4_flash_pp8": plan},
                    )
                    self.assertEqual(submitted, 4)
                    completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
                self.assertEqual((completed, failed, retried), (4, 0, 0))
                self.assertEqual(runner.batch_sizes, [4])
                status = api.dispatcher_status()
                self.assertEqual(status["last_summary"]["dispatch_mode"], "rolling_refill")
                self.assertEqual(status["last_summary"]["transport_mode"], "rolling_batch_incremental")
                self.assertEqual(status["resident_rolling_batch_count"], 1)
                self.assertEqual(status["resident_rolling_refill_stream_count"], 0)
        finally:
            if old is None:
                os.environ.pop("DS4_API_RESIDENT_PREFER_COHORT_BATCH", None)
            else:
                os.environ["DS4_API_RESIDENT_PREFER_COHORT_BATCH"] = old

    def test_resident_rolling_admission_blocks_early_parallel_same_service_cohorts_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            topology = SparkTopology.load(TOPOLOGY)
            plan = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)["dsv4_flash_pp8"]
            plan.admission_mode = "resident_multimodel_rolling_refill"
            plan.target_active = 96
            plan.queue_depth_target = 96
            plan.low_watermark = 84
            plan.max_cohort_size = 96

            self.assertEqual(api._resident_refill_limit(plan, {}, 0, 256), 96)
            self.assertEqual(api._resident_refill_limit(plan, {"dsv4_flash_pp8": 85}, 0, 256), 0)
            self.assertEqual(api._resident_refill_limit(plan, {"dsv4_flash_pp8": 57}, 0, 256), 96)

    def test_resident_rolling_admission_can_enable_parallel_same_service_cohorts(self) -> None:
        old = os.environ.get("DS4_API_RESIDENT_ALLOW_PARALLEL_COHORTS")
        os.environ["DS4_API_RESIDENT_ALLOW_PARALLEL_COHORTS"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                topology = SparkTopology.load(TOPOLOGY)
                plan = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)["dsv4_flash_pp8"]
                plan.admission_mode = "resident_multimodel_rolling_refill"
                plan.target_active = 96
                plan.queue_depth_target = 96
                plan.low_watermark = 84
                plan.max_cohort_size = 96

                self.assertEqual(api._resident_refill_limit(plan, {"dsv4_flash_pp8": 85}, 0, 256), 11)
                self.assertEqual(api._resident_refill_limit(plan, {"dsv4_flash_pp8": 57}, 0, 256), 96)
        finally:
            if old is None:
                os.environ.pop("DS4_API_RESIDENT_ALLOW_PARALLEL_COHORTS", None)
            else:
                os.environ["DS4_API_RESIDENT_ALLOW_PARALLEL_COHORTS"] = old

    def test_resident_multimodel_honors_compute_domain_batch_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            service_plans = {
                "qwen27_bf16_pp8": plans["qwen27_bf16_pp8"],
                "gemma4_26b_a4b_pp8": plans["gemma4_26b_a4b_pp8"],
            }
            for plan in service_plans.values():
                plan.admission_mode = "resident_multimodel_rolling_refill"
                plan.target_active = 1
                plan.queue_depth_target = 4
                plan.low_watermark = 1
                plan.max_cohort_size = 1
                plan.max_running_batches_per_compute_domain = 1
                plan.batch_linger_s = 0.0
            api.queue.submit_requests(
                requests=[
                    completion_request("domain-qwen", "prompt-qwen", profile_id="qwen3_6_27b_bf16_pp8_efficient_v1"),
                    completion_request("domain-gemma", "prompt-gemma", profile_id="gemma4_26b_a4b_it_pp8_peer_v1"),
                ],
                registry=registry,
                topology=topology,
                batch_id="domain-cap",
                priority=10,
            )
            runner = BlockingRefillIncrementalRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
            pending = {}
            with ThreadPoolExecutor(max_workers=2) as executor:
                submitted = api._dispatcher_refill_resident_multimodel(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"qwen27_bf16_pp8": 1, "gemma4_26b_a4b_pp8": 1},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans=service_plans,
                )
                self.assertEqual(submitted, 1)
                self.assertEqual(len(pending), 1)
                self.assertTrue(runner.wait_started(1))
                submitted = api._dispatcher_refill_resident_multimodel(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"qwen27_bf16_pp8": 1, "gemma4_26b_a4b_pp8": 1},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans=service_plans,
                )
                self.assertEqual(submitted, 0)
                self.assertEqual(api.dispatcher_status()["resident_compute_domain_active_batches"], {"spark-fleet-0": 1})
                self.assertEqual(api.dispatcher_status()["resident_compute_domain_batch_limits"], {"spark-fleet-0": 1})
                api.queue.cancel(batch_id="domain-cap", reason="test shutdown", force_running=True)
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (0, 0, 0))

    def test_resident_multimodel_honors_service_batch_cap_without_blocking_peers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            service_plans = {
                "qwen27_bf16_pp8": plans["qwen27_bf16_pp8"],
                "gemma4_26b_a4b_pp8": plans["gemma4_26b_a4b_pp8"],
            }
            for plan in service_plans.values():
                plan.admission_mode = "resident_multimodel_rolling_refill"
                plan.target_active = 1
                plan.queue_depth_target = 2
                plan.low_watermark = 1
                plan.max_cohort_size = 1
                plan.max_running_batches_per_compute_domain = 3
                plan.batch_linger_s = 0.0
            service_plans["qwen27_bf16_pp8"].max_running_batches_per_service = 1
            api.queue.submit_requests(
                requests=[
                    completion_request("service-cap-qwen-1", "prompt-qwen-1", profile_id="qwen3_6_27b_bf16_pp8_efficient_v1"),
                    completion_request("service-cap-qwen-2", "prompt-qwen-2", profile_id="qwen3_6_27b_bf16_pp8_efficient_v1"),
                    completion_request("service-cap-gemma", "prompt-gemma", profile_id="gemma4_26b_a4b_it_pp8_peer_v1"),
                ],
                registry=registry,
                topology=topology,
                batch_id="service-cap",
                priority=10,
            )
            runner = BlockingRefillIncrementalRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
            pending = {}
            with ThreadPoolExecutor(max_workers=2) as executor:
                try:
                    submitted = api._dispatcher_refill_resident_multimodel(
                        worker=worker,
                        executor=executor,
                        pending=pending,
                        entry_node_id="spark0",
                        node_profile_ids=tuple(topology.pipeline_profiles),
                        batch_limits_by_service={"qwen27_bf16_pp8": 1, "gemma4_26b_a4b_pp8": 1},
                        kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                        service_plans=service_plans,
                    )
                    self.assertEqual(submitted, 2)
                    self.assertEqual(api.dispatcher_status()["resident_service_active_batches"], {"qwen27_bf16_pp8": 1, "gemma4_26b_a4b_pp8": 1})
                    self.assertEqual(api.dispatcher_status()["resident_service_batch_limits"], {"qwen27_bf16_pp8": 1})
                    self.assertTrue(runner.wait_started(2))
                    submitted = api._dispatcher_refill_resident_multimodel(
                        worker=worker,
                        executor=executor,
                        pending=pending,
                        entry_node_id="spark0",
                        node_profile_ids=tuple(topology.pipeline_profiles),
                        batch_limits_by_service={"qwen27_bf16_pp8": 1, "gemma4_26b_a4b_pp8": 1},
                        kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                        service_plans=service_plans,
                    )
                    self.assertEqual(submitted, 0)
                finally:
                    api.queue.cancel(batch_id="service-cap", reason="test shutdown", force_running=True)
                    completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (0, 0, 0))

    def test_resident_rolling_admission_can_force_refill_stream_for_service(self) -> None:
        old = os.environ.get("DS4_API_RESIDENT_FORCE_REFILL_STREAM_SERVICE_IDS")
        os.environ["DS4_API_RESIDENT_FORCE_REFILL_STREAM_SERVICE_IDS"] = "dsv4_flash_pp8"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                registry = ProfileRegistry.load(PROFILES)
                topology = SparkTopology.load(TOPOLOGY)
                plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
                plan = plans["dsv4_flash_pp8"]
                plan.admission_mode = "resident_multimodel_rolling_refill"
                plan.target_active = 4
                plan.queue_depth_target = 4
                plan.low_watermark = 2
                plan.max_cohort_size = 4
                plan.batch_linger_s = 0.0
                requests = [dsv4_chat_request(f"dsv4-forced-stream-{index}") for index in range(4)]
                api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="forced-stream", priority=10)
                runner = RecordingHybridRunner()
                worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
                pending = {}
                with ThreadPoolExecutor(max_workers=1) as executor:
                    submitted = api._dispatcher_refill_resident_multimodel(
                        worker=worker,
                        executor=executor,
                        pending=pending,
                        entry_node_id="spark0",
                        node_profile_ids=tuple(topology.pipeline_profiles),
                        batch_limits_by_service={"dsv4_flash_pp8": 4},
                        kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                        service_plans={"dsv4_flash_pp8": plan},
                    )
                    self.assertEqual(submitted, 4)
                    completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
                self.assertEqual((completed, failed, retried), (4, 0, 0))
                self.assertEqual(runner.batch_sizes, [1, 1, 1, 1])
                self.assertEqual(runner.calls, [])
                status = api.dispatcher_status()
                self.assertEqual(status["last_summary"]["transport_mode"], "rolling_refill_stream")
                self.assertEqual(status["last_summary"]["batch_ineligible_reason"], "forced_refill_stream")
                self.assertEqual(status["last_summary"]["forced_refill_stream"], True)
                self.assertEqual(status["resident_rolling_batch_count"], 0)
                self.assertEqual(status["resident_rolling_refill_stream_count"], 1)
        finally:
            if old is None:
                os.environ.pop("DS4_API_RESIDENT_FORCE_REFILL_STREAM_SERVICE_IDS", None)
            else:
                os.environ["DS4_API_RESIDENT_FORCE_REFILL_STREAM_SERVICE_IDS"] = old

    def test_resident_rolling_admission_stops_refill_after_batch_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            plan = plans["dsv4_flash_pp8"]
            plan.admission_mode = "resident_multimodel_rolling_refill"
            plan.target_active = 2
            plan.low_watermark = 2
            plan.max_cohort_size = 2
            plan.batch_linger_s = 0.0
            api.queue.submit_requests(
                requests=[dsv4_chat_request(f"dsv4-cancel-{index}") for index in range(5)],
                registry=registry,
                topology=topology,
                batch_id="roll-cancel",
                priority=10,
            )
            runner = CancellingPerRequestRunner(lambda: api.queue.cancel(batch_id="roll-cancel", reason="test cancel", force_running=False))
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
            pending = {}
            with ThreadPoolExecutor(max_workers=1) as executor:
                submitted = api._dispatcher_refill_resident_multimodel(
                    worker=worker,
                    executor=executor,
                    pending=pending,
                    entry_node_id="spark0",
                    node_profile_ids=tuple(topology.pipeline_profiles),
                    batch_limits_by_service={"dsv4_flash_pp8": 2},
                    kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                    service_plans={"dsv4_flash_pp8": plan},
                )
                self.assertEqual(submitted, 2)
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (0, 0, 0))
            self.assertLessEqual(len(runner.calls), 2)
            self.assertEqual(api.queue.status(batch_id="roll-cancel")["state"], "cancelled")
            self.assertEqual(api.dispatcher_status()["last_summary"]["dispatch_mode"], "rolling_refill")
            self.assertEqual(api.dispatcher_status()["last_summary"]["claimed"], 2)

    def test_worker_force_cancel_terminal_cancels_rolling_refill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
            plan = plans["dsv4_flash_pp8"]
            plan.admission_mode = "resident_multimodel_rolling_refill"
            plan.target_active = 2
            plan.low_watermark = 2
            plan.max_cohort_size = 2
            plan.batch_linger_s = 0.0
            api.queue.submit_requests(requests=[dsv4_chat_request(f"dsv4-force-cancel-{index}") for index in range(2)], registry=registry, topology=topology, batch_id="roll-force-cancel", priority=10)
            runner = BlockingPerRequestRunner()
            worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
            pending = {}
            with ThreadPoolExecutor(max_workers=1) as executor:
                submitted = api._dispatcher_refill_resident_multimodel(worker=worker, executor=executor, pending=pending, entry_node_id="spark0", node_profile_ids=tuple(topology.pipeline_profiles), batch_limits_by_service={"dsv4_flash_pp8": 2}, kv_shard_layouts_by_profile=dict(topology.pipeline_profiles), service_plans={"dsv4_flash_pp8": plan})
                self.assertEqual(submitted, 2)
                self.assertTrue(runner.wait_started(2))
                api.queue.cancel(batch_id="roll-force-cancel", reason="operator cancel", force_running=True)
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=False)
                self.assertEqual((completed, failed, retried), (0, 0, 0))
                self.assertEqual(len(pending), 1)
                for request_id in ("dsv4-force-cancel-0", "dsv4-force-cancel-1"):
                    self.assertEqual(api.queue.status(request_id=request_id)["state"], "cancelled")
                    self.assertFalse(api.queue.status(request_id=request_id)["cancel_requested"])
                runner.release.set()
                completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
            self.assertEqual((completed, failed, retried), (0, 0, 0))
            self.assertEqual(pending, {})
            self.assertEqual(api.queue.status(batch_id="roll-force-cancel")["state"], "cancelled")
            self.assertEqual(api.dispatcher_status()["last_summary"]["dispatch_mode"], "rolling_refill")
            self.assertEqual(api.dispatcher_status()["last_summary"]["claimed"], 2)

    def test_forced_rolling_refill_cancel_reaches_incremental_transport(self) -> None:
        old_force = os.environ.get("DS4_API_RESIDENT_FORCE_REFILL_STREAM")
        os.environ["DS4_API_RESIDENT_FORCE_REFILL_STREAM"] = "1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                registry = ProfileRegistry.load(PROFILES)
                topology = SparkTopology.load(TOPOLOGY)
                plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)
                plan = plans["dsv4_flash_pp8"]
                plan.admission_mode = "resident_multimodel_rolling_refill"
                plan.target_active = 2
                plan.low_watermark = 2
                plan.max_cohort_size = 2
                plan.batch_linger_s = 0.0
                api.queue.submit_requests(requests=[dsv4_chat_request(f"dsv4-stream-cancel-{index}") for index in range(2)], registry=registry, topology=topology, batch_id="roll-stream-cancel", priority=10)
                runner = BlockingRefillIncrementalRunner()
                worker = BatchWorker(queue=api.queue, registry=registry, runner=runner, worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=0.01)
                pending = {}
                with ThreadPoolExecutor(max_workers=1) as executor:
                    submitted = api._dispatcher_refill_resident_multimodel(worker=worker, executor=executor, pending=pending, entry_node_id="spark0", node_profile_ids=tuple(topology.pipeline_profiles), batch_limits_by_service={"dsv4_flash_pp8": 2}, kv_shard_layouts_by_profile=dict(topology.pipeline_profiles), service_plans={"dsv4_flash_pp8": plan})
                    self.assertEqual(submitted, 2)
                    self.assertTrue(runner.wait_started(2))
                    api.queue.cancel(batch_id="roll-stream-cancel", reason="operator cancel", force_running=True)
                    completed, failed, retried = api._dispatcher_finish_done(worker, pending, block=True)
                self.assertEqual((completed, failed, retried), (0, 0, 0))
                self.assertEqual(runner.batch_sizes, [1, 1])
                self.assertTrue(runner.cancel_seen.wait(1.0))
                self.assertEqual(pending, {})
                self.assertEqual(api.queue.status(batch_id="roll-stream-cancel")["state"], "cancelled")
                self.assertEqual(api.dispatcher_status()["last_summary"]["transport_mode"], "rolling_refill_stream")
        finally:
            if old_force is None:
                os.environ.pop("DS4_API_RESIDENT_FORCE_REFILL_STREAM", None)
            else:
                os.environ["DS4_API_RESIDENT_FORCE_REFILL_STREAM"] = old_force

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

    def test_dispatcher_status_reports_resident_targets_before_first_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            status = api.dispatcher_status()

            self.assertTrue(status["resident_multimodel"])
            self.assertEqual(status["resident_service_targets"]["dsv4_flash_pp8"], 64)
            self.assertEqual(status["resident_service_queue_depth_targets"]["dsv4_flash_pp8"], 64)
            self.assertEqual(status["resident_compute_domain_batch_limits"], {"spark-fleet-0": 1})
            self.assertIn("dsv4_flash_pp8", status["resident_service_admission_modes"])

    def test_dispatcher_status_clears_stale_active_compute_domain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            with api.dispatcher_lock:
                api.dispatcher_state.update(
                    pending=0,
                    pending_cohort_details=[],
                    resident_compute_domain_active_batches={"spark-fleet-0": 1},
                )

            status = api.dispatcher_status()

            self.assertEqual(status["resident_compute_domain_active_batches"], {})
            self.assertEqual(status["resident_compute_domain_batch_limits"], {"spark-fleet-0": 1})

    def test_dispatcher_status_keeps_drained_rolling_batch_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            with api.dispatcher_lock:
                api.dispatcher_state.update(
                    pending=1,
                    pending_cohorts=1,
                    pending_cohort_details=[
                        {
                            "service_id": "dsv4_flash_pp8",
                            "compute_domain": "spark-fleet-0",
                            "admission_mode": "rolling_refill",
                            "initial_count": 4,
                            "active_count": 0,
                            "batch_active": True,
                        }
                    ],
                )

            status = api.dispatcher_status()

            self.assertEqual(status["resident_service_active_batches"], {"dsv4_flash_pp8": 1})
            self.assertEqual(status["resident_compute_domain_active_batches"], {"spark-fleet-0": 1})
            self.assertEqual(status["resident_compute_domain_batch_limits"], {"spark-fleet-0": 1})

    def test_dispatcher_status_reports_live_queue_counts_by_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            api.queue.submit_requests(
                requests=[dsv4_chat_request("live-0"), dsv4_chat_request("live-1")],
                registry=registry,
                topology=topology,
                batch_id="live-counts",
                priority=10,
            )
            api.queue.prepare_ready(
                node_id="spark0",
                eligible_profile_ids=tuple(topology.pipeline_profiles),
                batch_id="live-counts",
                limit=2,
                leased_by="worker",
                lease_ttl_s=30,
                selected_service_id="dsv4_flash_pp8",
                share_compute_domain=True,
            )
            claims = api.queue.claim_ready_batch(
                node_id="spark0",
                batch_id="live-counts",
                limit=2,
                leased_by="worker",
                lease_ttl_s=30,
                selected_service_id="dsv4_flash_pp8",
                share_compute_domain=True,
            )
            self.assertEqual(len(claims), 2)
            api.queue.finish_request(
                request_id=claims[0].request_id,
                lease_id=claims[0].lease_id,
                state="completed",
                result=make_result(request=claims[0].request, profile_id=claims[0].selected_profile_id, model_id="test", backend="fake", text="done"),
            )

            status = api.dispatcher_status()

            service_counts = status["queue_state_counts_by_service"]["dsv4_flash_pp8"]
            self.assertEqual(service_counts["completed"], 1)
            self.assertEqual(service_counts["running"], 1)
            self.assertEqual(status["queue_unfinished_by_service"]["dsv4_flash_pp8"], 1)
            self.assertEqual(status["queue_running_by_service"]["dsv4_flash_pp8"], 1)

    def test_resource_governor_defaults_to_host_for_local_sampling(self) -> None:
        old_value = os.environ.get("DS4_API_RESOURCE_LOCAL_NODE_ID")
        os.environ.pop("DS4_API_RESOURCE_LOCAL_NODE_ID", None)
        try:
            governor = GpuResourceGovernor.from_env(nodes=("spark0",), local_node_id="spark0")
            self.assertEqual(governor.local_node_id, socket.gethostname())
            os.environ["DS4_API_RESOURCE_LOCAL_NODE_ID"] = "spark0"
            explicit = GpuResourceGovernor.from_env(nodes=("spark0",), local_node_id="ignored")
            self.assertEqual(explicit.local_node_id, "spark0")
        finally:
            if old_value is None:
                os.environ.pop("DS4_API_RESOURCE_LOCAL_NODE_ID", None)
            else:
                os.environ["DS4_API_RESOURCE_LOCAL_NODE_ID"] = old_value

    def test_resource_governor_status_refreshes_stale_sample(self) -> None:
        old_values = {
            "DS4_API_RESOURCE_GOVERNOR": os.environ.get("DS4_API_RESOURCE_GOVERNOR"),
            "DS4_API_RESOURCE_SAMPLE_JSON": os.environ.get("DS4_API_RESOURCE_SAMPLE_JSON"),
            "DS4_API_RESOURCE_POLL_S": os.environ.get("DS4_API_RESOURCE_POLL_S"),
        }
        os.environ["DS4_API_RESOURCE_GOVERNOR"] = "1"
        os.environ["DS4_API_RESOURCE_SAMPLE_JSON"] = json.dumps({"nodes": {"spark0": {"temperature_c": 50, "power_w": 40, "utilization_pct": 3}}})
        os.environ["DS4_API_RESOURCE_POLL_S"] = "1000"
        try:
            governor = GpuResourceGovernor.from_env(nodes=("spark0",), local_node_id="spark0")
            first = governor.before_refill().status
            self.assertEqual(first["max_utilization_pct"], 3.0)
            self.assertEqual(first["max_utilization_node"], "spark0")
            governor.sample_json = json.dumps({"nodes": {"spark0": {"temperature_c": 51, "power_w": 41, "utilization_pct": 89}}})
            reused = governor.status(refresh=True)
            self.assertEqual(reused["max_utilization_pct"], 3.0)
            self.assertEqual(reused["max_utilization_node"], "spark0")
            governor.poll_s = 0.1
            governor._last_sample_at = time.time() - 10.0
            refreshed = governor.status(refresh=True)
            self.assertEqual(refreshed["max_utilization_pct"], 89.0)
            self.assertEqual(refreshed["max_utilization_node"], "spark0")
            self.assertEqual(refreshed["last_decision"], "status_refresh")
            self.assertIsNotNone(refreshed["sample_age_s"])
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_vllm_metrics_snapshot_reports_running_progress(self) -> None:
        text = "\n".join(
            [
                'vllm:num_requests_running{engine="0",model_name="kimi27-code-pp13"} 1.0',
                'vllm:num_requests_waiting{engine="0",model_name="kimi27-code-pp13"} 0.0',
                'vllm:prompt_tokens_total{engine="0",model_name="kimi27-code-pp13"} 126901.0',
                'vllm:prompt_tokens_by_source_total{engine="0",model_name="kimi27-code-pp13",source="local_compute"} 126901.0',
                'vllm:prompt_tokens_by_source_total{engine="0",model_name="kimi27-code-pp13",source="local_cache_hit"} 0.0',
                'vllm:generation_tokens_total{engine="0",model_name="kimi27-code-pp13"} 2199.0',
                'vllm:prompt_tokens_cached_total{engine="0",model_name="kimi27-code-pp13"} 0.0',
                'vllm:time_to_first_token_seconds_count{engine="0",model_name="kimi27-code-pp13"} 1.0',
                'vllm:time_to_first_token_seconds_sum{engine="0",model_name="kimi27-code-pp13"} 321.5558202266693',
                'vllm:request_success_total{engine="0",finished_reason="stop",model_name="kimi27-code-pp13"} 0.0',
                'vllm:request_success_total{engine="0",finished_reason="length",model_name="kimi27-code-pp13"} 0.0',
            ]
        )
        status = _parse_vllm_metrics_snapshot(text)
        self.assertEqual(status["num_requests_running"], 1.0)
        self.assertEqual(status["num_requests_waiting"], 0.0)
        self.assertEqual(status["prompt_tokens_total"], 126901.0)
        self.assertEqual(status["generation_tokens_total"], 2199.0)
        self.assertEqual(status["prompt_tokens_cached_total"], 0.0)
        self.assertEqual(status["prompt_tokens_by_source_total"]["local_compute"], 126901.0)
        self.assertEqual(status["prompt_tokens_by_source_total"]["local_cache_hit"], 0.0)
        self.assertEqual(status["request_success_total"]["stop"], 0.0)
        self.assertEqual(status["request_success_total"]["length"], 0.0)
        self.assertEqual(status["time_to_first_token_avg_s"], 321.556)

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

    def test_resource_governor_host_memory_delays_dispatcher_refill(self) -> None:
        old_values = {
            "DS4_API_RESOURCE_GOVERNOR": os.environ.get("DS4_API_RESOURCE_GOVERNOR"),
            "DS4_API_RESOURCE_SAMPLE_JSON": os.environ.get("DS4_API_RESOURCE_SAMPLE_JSON"),
            "DS4_API_RESOURCE_HOST_MEMORY_SOFT_PCT": os.environ.get("DS4_API_RESOURCE_HOST_MEMORY_SOFT_PCT"),
            "DS4_API_RESOURCE_HOST_MEMORY_HARD_PCT": os.environ.get("DS4_API_RESOURCE_HOST_MEMORY_HARD_PCT"),
            "DS4_API_RESOURCE_THROTTLE_STEP_S": os.environ.get("DS4_API_RESOURCE_THROTTLE_STEP_S"),
        }
        os.environ["DS4_API_RESOURCE_GOVERNOR"] = "1"
        os.environ["DS4_API_RESOURCE_SAMPLE_JSON"] = json.dumps({"nodes": {"spark0": {"temperature_c": 55, "power_w": 95, "utilization_pct": 72, "host_memory_used_mib": 91, "host_memory_total_mib": 100}}})
        os.environ["DS4_API_RESOURCE_HOST_MEMORY_SOFT_PCT"] = "90"
        os.environ["DS4_API_RESOURCE_HOST_MEMORY_HARD_PCT"] = "95"
        os.environ["DS4_API_RESOURCE_THROTTLE_STEP_S"] = "0.1"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                registry = ProfileRegistry.load(PROFILES)
                topology = SparkTopology.load(TOPOLOGY)
                requests = [completion_request("mem0")]
                api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="mem", priority=10)
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
                self.assertIn("host_memory_soft", status["resource_governor"]["throttle_reasons"])
                self.assertEqual(status["resource_governor"]["max_host_memory_node"], "spark0")
                self.assertEqual(status["resource_governor"]["max_host_memory_used_pct"], 91.0)
                self.assertEqual(status["resource_governor_throttle_count"], 1)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_resource_governor_free_parser_uses_memavailable(self) -> None:
        parsed = _parse_free_m(
            "               total        used        free      shared  buff/cache   available\n"
            "Mem:            1000         990          10           0         390         400\n"
            "Swap:              0           0           0\n"
        )
        self.assertEqual(parsed["host_memory_total_mib"], 1000.0)
        self.assertEqual(parsed["host_memory_available_mib"], 400.0)
        self.assertEqual(parsed["host_memory_available_pct"], 40.0)
        self.assertEqual(parsed["host_memory_used_mib"], 600.0)
        self.assertEqual(parsed["host_memory_used_pct"], 60.0)

    def test_resource_governor_does_not_sample_when_queue_is_idle(self) -> None:
        old_values = {
            "DS4_API_RESOURCE_GOVERNOR": os.environ.get("DS4_API_RESOURCE_GOVERNOR"),
            "DS4_API_RESOURCE_SAMPLE_JSON": os.environ.get("DS4_API_RESOURCE_SAMPLE_JSON"),
            "DS4_API_RESOURCE_TEMP_SOFT_C": os.environ.get("DS4_API_RESOURCE_TEMP_SOFT_C"),
            "DS4_API_RESOURCE_TEMP_HARD_C": os.environ.get("DS4_API_RESOURCE_TEMP_HARD_C"),
        }
        os.environ["DS4_API_RESOURCE_GOVERNOR"] = "1"
        os.environ["DS4_API_RESOURCE_SAMPLE_JSON"] = json.dumps({"nodes": {"spark0": {"temperature_c": 91, "power_w": 95, "utilization_pct": 96}}})
        os.environ["DS4_API_RESOURCE_TEMP_SOFT_C"] = "86"
        os.environ["DS4_API_RESOURCE_TEMP_HARD_C"] = "88"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                topology = SparkTopology.load(TOPOLOGY)
                worker = BatchWorker(queue=api.queue, registry=ProfileRegistry.load(PROFILES), runner=RecordingBatchRunner(), worker_id="test-dispatcher", lease_ttl_s=30, heartbeat_interval_s=1.0)
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
                self.assertEqual(status["resource_governor"]["sampled_nodes"], 0)
                self.assertFalse(status["resource_governor"]["throttle_active"])
                self.assertEqual(status["resource_governor_throttle_count"], 0)
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
