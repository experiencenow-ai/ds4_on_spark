from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys
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


if __name__ == "__main__":
    unittest.main()
