from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import _openai_payload
from ds4_infer.schemas import InferenceRequest

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
SCRIPT = ROOT / "scripts" / "ds4_api_queue_benchmark.py"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bench = load_script_module("ds4_api_queue_benchmark", SCRIPT)


class ApiQueueBenchmarkTests(unittest.TestCase):
    def test_benchmark_requests_force_decode_length_by_default(self) -> None:
        args = argparse.Namespace(input_tokens=8, output_tokens=256, temperature=0.0, job_class="analysis", ignore_eos=True)
        request = bench._request_json(args, "batch-a", "profile-a", 3)
        self.assertEqual(request["input"]["openai"], {"ignore_eos": True, "min_tokens": 256})

    def test_benchmark_requests_attach_external_kv_plan(self) -> None:
        args = argparse.Namespace(
            input_tokens=8,
            output_tokens=256,
            temperature=0.0,
            job_class="analysis",
            ignore_eos=True,
            external_kv_key="prefix-a",
            external_kv_namespace="bench",
            external_kv_service_id="dsv4_flash_pp8",
            external_kv_backend="lmcache",
            external_kv_mode="require",
            external_kv_miss_policy="fail",
            external_kv_route_affinity="required",
            external_kv_prefix_hash="sha256:abc",
            external_kv_total_bytes=4096,
        )
        request = bench._request_json(args, "batch-a", "profile-a", 0)
        plan = request["input"]["kv_cache_plan"]
        self.assertEqual(plan["format"], "ds4-kv-cache-plan-v1")
        self.assertEqual(plan["load"]["transport"], "external_manifest")
        self.assertEqual(plan["load"]["service_id"], "dsv4_flash_pp8")
        self.assertEqual(plan["miss_policy"], "fail")
        self.assertEqual(request["input"]["kv_cache_key"], "prefix-a")
        self.assertEqual(request["input"]["kv_bytes_estimate"], 4096)

    def test_benchmark_requests_attach_exact_kv_cache_directive(self) -> None:
        directive = {"format": "ds4-kv-cache-directive-v1", "cache_id": "cache-a", "load": {"mode": "prefer", "transport": "local_store", "path": "node-local://spark0/cache-a"}}
        args = argparse.Namespace(input_tokens=8, output_tokens=256, temperature=0.0, job_class="analysis", ignore_eos=True, kv_cache_directive_json=json.dumps(directive, sort_keys=True))
        request = bench._request_json(args, "batch-a", "profile-a", 0)
        self.assertEqual(request["input"]["kv_cache"], directive)

    def test_benchmark_shared_prefix_splits_suffix(self) -> None:
        args = argparse.Namespace(input_tokens=10, shared_prefix_tokens=6, suffix_tokens=None)
        prompt = bench._prompt(args, 2)
        self.assertEqual(prompt.count("shared-prefix-benchmark"), 6)
        self.assertEqual(prompt.count("request-specific-detail"), 4)

    def test_bubble_corrected_two_spark_equivalent_score(self) -> None:
        score = bench._performance_score(aggregate_tok_s=420.0, concurrency=64, pipeline_stages=8, equivalent_sparks=2, reference_tok_s=144.6)
        self.assertEqual(score["aggregate_tok_s_needed_for_reference"], 521.374648)
        self.assertEqual(score["aggregate_tok_s_needed_for_80pct_reference"], 417.099718)
        self.assertEqual(score["two_spark_equivalent_tok_s"], 116.484375)

    def test_openai_runner_forwards_benchmark_sampling_fields(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "req-a",
                "capability": None,
                "chat": False,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 256,
                "thinking_budget_tokens": 0,
                "temperature": 0.0,
                "input": {"prompt": "hello", "openai": {"ignore_eos": True, "min_tokens": 256}},
                "output_contract": {"format": "text"},
                "model_pin": {"profile_id": profile.profile_id},
            }
        )
        payload = _openai_payload(request, profile)
        self.assertEqual(payload["ignore_eos"], True)
        self.assertEqual(payload["min_tokens"], 256)

    def test_file_driven_request_jsonl_round_trip(self) -> None:
        args = argparse.Namespace(input_tokens=8, output_tokens=128, temperature=0.0, job_class="analysis", ignore_eos=True)
        requests = [bench._request_json(args, "batch-file", "profile-a", idx) for idx in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "requests.jsonl"
            bench._write_requests_jsonl(path, requests)
            loaded = bench._load_requests_jsonl(path)
        self.assertEqual([item["request_id"] for item in loaded], ["batch-file-000000", "batch-file-000001", "batch-file-000002"])
        self.assertEqual(bench._target_completion_tokens(loaded), 384)

    def test_file_driven_replay_remaps_request_ids(self) -> None:
        loaded = [
            {"request_id": "old-batch-000000", "max_output_tokens": 128, "input": {"prompt": "a"}},
            {"request_id": "old-batch-000001", "max_output_tokens": 128, "input": {"prompt": "b"}},
        ]
        remapped = bench._remap_request_ids(loaded, "new-batch")
        self.assertEqual([item["request_id"] for item in remapped], ["new-batch-000000", "new-batch-000001"])
        self.assertEqual([item["request_id"] for item in loaded], ["old-batch-000000", "old-batch-000001"])
        self.assertEqual(remapped[1]["input"]["prompt"], "b")

    def test_file_driven_manifest_marks_external_worker(self) -> None:
        args = argparse.Namespace(base_url="http://127.0.0.1:8700", model="dsv4", input_tokens=128, output_tokens=256, concurrency=256, limit=256, drive_worker=False, ignore_eos=True, preserve_request_ids=False)
        manifest = bench._manifest_json(args, "batch-file", [{"request_id": "a"}])
        self.assertEqual(manifest["format"], "ds4-api-file-driven-benchmark-manifest-v1")
        self.assertEqual(manifest["worker_mode"], "external_worker")
        self.assertEqual(manifest["requests_jsonl"], "requests.jsonl")
        self.assertEqual(manifest["preserved_request_ids"], False)
        self.assertEqual(manifest["cache_mode"], "cold_unique_prefix")

    def test_file_driven_manifest_uses_replayed_completion_target(self) -> None:
        args = argparse.Namespace(base_url="http://127.0.0.1:8700", model="dsv4", input_tokens=128, output_tokens=256, concurrency=256, limit=256, drive_worker=False, ignore_eos=True, preserve_request_ids=False)
        manifest = bench._manifest_json(args, "batch-file", [{"request_id": "a", "max_output_tokens": 128}, {"request_id": "b", "max_output_tokens": 128}])
        self.assertEqual(manifest["output_tokens_target"], 128)
        self.assertEqual(manifest["completion_tokens_target"], 256)
        self.assertEqual(manifest["min_tokens"], 128)

    def test_result_timings_expose_transport_retries(self) -> None:
        results = [
            {
                "request": {"created_at": 10.0, "started_at": 20.0, "completed_at": 60.0, "attempt_count": 2},
                "result": {"transport": {"duration_s": 40.0}},
            },
            {
                "request": {"created_at": 10.0, "started_at": 20.0, "completed_at": 61.0, "attempt_count": 2},
                "result": {"transport": {"duration_s": 41.0}},
            },
        ]
        timings = bench._result_timings(results, run_s=100.0)
        self.assertEqual(timings["attempt_count_max"], 2)
        self.assertEqual(timings["queue_wait_s"], 10.0)
        self.assertEqual(timings["request_window_s"], 41.0)
        self.assertEqual(timings["transport_duration_s_max"], 41.0)


if __name__ == "__main__":
    unittest.main()
