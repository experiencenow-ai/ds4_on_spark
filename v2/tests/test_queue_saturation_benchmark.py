from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue
from ds4_infer.schemas import make_result

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
SCRIPT = ROOT / "scripts" / "ds4_queue_saturation.py"
CALIBRATE_SCRIPT = ROOT / "scripts" / "ds4_spark_batch_shape_calibrate.py"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sat = load_script_module("ds4_queue_saturation", SCRIPT)
calibrate = load_script_module("ds4_spark_batch_shape_calibrate", CALIBRATE_SCRIPT)


class TokenRunner:
    def run_one(self, request, profile):
        time.sleep(0.01)
        result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text="x" * 64)
        result["usage"]["completion_tokens"] = 123
        return result


class QueueSaturationBenchmarkTests(unittest.TestCase):
    def test_stress_ladder_parses_depth_and_concurrency_pairs(self) -> None:
        points = sat.parse_stress_ladder("1x1,2:4,8")
        self.assertEqual([(item.target_depth, item.worker_concurrency) for item in points], [(1, 1), (2, 4), (8, 8)])

    def test_gpu_samples_have_ordered_vector_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gpu_samples.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "gpu_nodes": ["spark0", "spark1", "spark2"],
                        "gpu_util_vector": [95.0, 40.0, None],
                        "nodes": {
                            "spark0": {"ok": True, "gpu_util": 95.0},
                            "spark1": {"ok": True, "gpu_util": 40.0},
                            "spark2": {"ok": False, "error": "offline"},
                        },
                    },
                    sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
            gpu = sat.summarize_gpu(path, threshold=90.0, interval_s=1.0)
            vector = sat.summarize_gpu_vector(path, gpu)
        self.assertEqual(vector["nodes"], ["spark0", "spark1", "spark2"])
        self.assertEqual(vector["avg_gpu"], [95.0, 40.0, 0.0])
        self.assertEqual(vector["active_seconds"], [1.0, 0.0, 0.0])

    def test_throughput_uses_completion_tokens_from_finished_requests(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_fp8_efficient_v1")
        with tempfile.TemporaryDirectory() as tmp:
            queue = InferenceQueue(tmp)
            requests = [sat.make_request(profile, "r0"), sat.make_request(profile, "r1")]
            queue.submit_requests(requests=requests, registry=registry, batch_id="batch-a")
            queue.work(registry=registry, runner=TokenRunner(), limit=2, concurrency=2)
            summary = sat.summarize_throughput(Path(tmp) / "queue.sqlite3")
        self.assertEqual(summary["completed_requests"], 2)
        self.assertEqual(summary["completion_tokens"], 246)
        self.assertEqual(summary["actual_completion_tokens"], 246)
        self.assertGreater(summary["aggregate_completion_tok_s"], 0.0)

    def test_shape_calibration_uses_qwen_thinking_template_and_total_cap(self) -> None:
        enabled = calibrate.make_item(calibrate.Shape("Qwen/Qwen3.6-27B-FP8", 128, 64, 100), 0)
        disabled = calibrate.make_item(calibrate.Shape("Qwen/Qwen3.6-27B-FP8", 128, 64, 0), 0)
        self.assertEqual(enabled["max_tokens"], 164)
        self.assertEqual(enabled["thinking_token_budget"], 100)
        self.assertEqual(enabled["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(disabled["max_tokens"], 64)
        self.assertEqual(disabled["chat_template_kwargs"], {"enable_thinking": False})


if __name__ == "__main__":
    unittest.main()
