from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import tempfile
import threading
import time
import unittest

from ds4_infer.api import CoordinatorApi
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import OpenAICompatibleRunner
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology
from ds4_infer.worker import BatchWorker


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"


def completion_request(request_id: str, prompt: str = "prompt") -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": "efficient",
            "chat": False,
            "immediate": False,
            "job_class": "summary",
            "max_output_tokens": 32,
            "thinking_budget_tokens": 0,
            "temperature": 0.0,
            "input": {"prompt": prompt, "openai": {"ignore_eos": True, "min_tokens": 32}},
            "output_contract": {"format": "text"},
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
