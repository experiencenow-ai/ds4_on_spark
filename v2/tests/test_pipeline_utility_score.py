from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_pipeline_utility_score.py"
KIMI_TRIAD_BUDGET = ROOT / "profiles" / "production" / "kimi_qwen_gemma13_resident_memory_budget.json"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return(module)


score = load_script_module("ds4_pipeline_utility_score", SCRIPT)


class PipelineUtilityScoreTests(unittest.TestCase):
    def test_kv_target_range_keeps_full_score(self) -> None:
        service = {
            "service_id": "kimi27_pp13",
            "pipeline_parallel_size": 13,
            "batch_size": 32,
            "input_budget_tokens": 8192,
            "output_budget_tokens": 4096,
            "assumed_decode_tok_s": 20,
            "kv_resident_input_batches": 3.0,
        }

        result = score.score_service(service, {"target_batch_per_pipeline_stage": 2.0, "min_input_budget_tokens": 8192, "min_output_budget_tokens": 4096, "min_kv_resident_input_batches": 2.0, "preferred_kv_resident_input_batches": 3.0})

        self.assertEqual(result["kv_status"], "target")
        self.assertEqual(result["kv_efficiency"], 1.0)
        self.assertEqual(result["batch_factor"], 1.0)
        self.assertEqual(result["score"], 20.0)

    def test_oversized_kv_residency_is_penalized(self) -> None:
        service = {
            "service_id": "kimi27_pp13",
            "pipeline_parallel_size": 13,
            "batch_size": 32,
            "input_budget_tokens": 8192,
            "output_budget_tokens": 4096,
            "assumed_decode_tok_s": 20,
            "kv_resident_input_batches": 6.0,
        }

        result = score.score_service(service, {"target_batch_per_pipeline_stage": 2.0, "min_input_budget_tokens": 8192, "min_output_budget_tokens": 4096, "min_kv_resident_input_batches": 2.0, "preferred_kv_resident_input_batches": 3.0})

        self.assertEqual(result["kv_status"], "over_resident")
        self.assertEqual(result["kv_efficiency"], 0.5)
        self.assertEqual(result["score"], 10.0)

    def test_under_resident_kv_fails_closed(self) -> None:
        service = {
            "service_id": "kimi27_pp13",
            "pipeline_parallel_size": 13,
            "batch_size": 32,
            "input_budget_tokens": 8192,
            "output_budget_tokens": 4096,
            "assumed_decode_tok_s": 20,
            "kv_resident_input_batches": 1.5,
        }

        result = score.score_service(service, {"target_batch_per_pipeline_stage": 2.0, "min_input_budget_tokens": 8192, "min_output_budget_tokens": 4096, "min_kv_resident_input_batches": 2.0, "preferred_kv_resident_input_batches": 3.0})

        self.assertEqual(result["kv_status"], "under_resident")
        self.assertEqual(result["kv_efficiency"], 0.0)
        self.assertEqual(result["score"], 0.0)

    def test_kimi_triad_budget_declares_metric_contract(self) -> None:
        budget = json.loads(KIMI_TRIAD_BUDGET.read_text(encoding="utf-8"))
        metric = budget["throughput_utility_metric"]

        self.assertEqual(metric["format"], "ds4-centaur-throughput-utility-v1")
        self.assertEqual(metric["defaults"]["target_batch_per_pipeline_stage"], 2.0)
        self.assertEqual(metric["defaults"]["min_input_budget_tokens"], 8192)
        self.assertEqual(metric["defaults"]["min_output_budget_tokens"], 4096)
        self.assertEqual(metric["defaults"]["min_kv_resident_input_batches"], 2.0)
        self.assertEqual(metric["defaults"]["preferred_kv_resident_input_batches"], 3.0)
        self.assertTrue(metric["hard_constraints"]["strict_kv_eviction_required"])
        self.assertEqual({item["service_id"] for item in metric["service_candidates"]}, {"kimi27_pp13", "qwen27_bf16_pp13", "gemma4_26b_a4b_pp13"})
        self.assertEqual(metric["service_candidates"][2]["batch_size"], 16)
        self.assertEqual(metric["service_candidates"][0]["gpu_memory_utilization"], 0.254)
        self.assertEqual({item["pipeline_id"] for item in metric["pipeline_candidates"]}, {"centaur_kimi_qwen_gemma_pp13", "centaur_qwen_gemma_fast_pair", "centaur_kimi_smart_lane"})

    def test_optimizer_blocks_over_cap_triad(self) -> None:
        payload = {
            "throughput_utility_metric": {
                "defaults": {"target_batch_per_pipeline_stage": 2.0, "min_input_budget_tokens": 8192, "min_output_budget_tokens": 4096, "min_kv_resident_input_batches": 2.0, "preferred_kv_resident_input_batches": 3.0},
                "hard_constraints": {"active_gpu_memory_utilization_sum_max": 0.85, "strict_kv_eviction_required": True},
                "service_candidates": [
                    {"service_id": "kimi", "pipeline_parallel_size": 13, "gpu_memory_utilization": 0.7, "batch_size": 32, "input_budget_tokens": 8192, "output_budget_tokens": 4096, "assumed_decode_tok_s": 20, "kv_resident_input_batches": 3.0},
                    {"service_id": "qwen", "pipeline_parallel_size": 13, "gpu_memory_utilization": 0.25, "batch_size": 32, "input_budget_tokens": 8192, "output_budget_tokens": 4096, "assumed_decode_tok_s": 200, "kv_resident_input_batches": 3.0},
                    {"service_id": "gemma", "pipeline_parallel_size": 13, "gpu_memory_utilization": 0.2, "batch_size": 32, "input_budget_tokens": 8192, "output_budget_tokens": 4096, "assumed_decode_tok_s": 160, "kv_resident_input_batches": 3.0},
                ],
                "pipeline_candidates": [
                    {"pipeline_id": "triad", "service_ids": ["kimi", "qwen", "gemma"]},
                    {"pipeline_id": "fast_pair", "service_ids": ["qwen", "gemma"]},
                    {"pipeline_id": "smart_lane", "service_ids": ["kimi"]},
                ],
            }
        }

        result = score.optimize_payload(payload)
        by_id = {item["pipeline_id"]: item for item in result["candidates"]}

        self.assertFalse(by_id["triad"]["eligible"])
        self.assertIn("gpu_utilization_sum 1.150 > 0.850", by_id["triad"]["violations"])
        self.assertTrue(by_id["fast_pair"]["eligible"])
        self.assertTrue(by_id["smart_lane"]["eligible"])
        self.assertGreater(by_id["fast_pair"]["score"], by_id["smart_lane"]["score"])

    def test_optimizer_expands_batch_and_kv_candidates(self) -> None:
        payload = {
            "throughput_utility_metric": {
                "defaults": {"target_batch_per_pipeline_stage": 2.0, "min_input_budget_tokens": 8192, "min_output_budget_tokens": 4096, "min_kv_resident_input_batches": 2.0, "preferred_kv_resident_input_batches": 3.0},
                "hard_constraints": {"active_gpu_memory_utilization_sum_max": 0.85, "strict_kv_eviction_required": True},
                "service_candidates": [
                    {
                        "service_id": "kimi",
                        "pipeline_parallel_size": 13,
                        "gpu_memory_utilization": 0.5,
                        "batch_size_candidates": [16, 32],
                        "input_budget_tokens": 8192,
                        "output_budget_tokens": 4096,
                        "assumed_decode_tok_s": 20,
                        "kv_resident_input_batches_candidates": [1.5, 2.0, 3.0],
                    }
                ],
            }
        }

        result = score.optimize_payload(payload)
        eligible = [item for item in result["candidates"] if item["eligible"]]

        self.assertEqual(result["candidate_count"], 6)
        self.assertEqual(result["eligible_count"], 4)
        self.assertEqual(eligible[0]["services"][0]["batch_size"], 32)
        self.assertEqual(eligible[0]["services"][0]["kv_status"], "target")


if __name__ == "__main__":
    unittest.main()
