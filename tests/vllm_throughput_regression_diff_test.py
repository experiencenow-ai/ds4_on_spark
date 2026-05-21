import json
import tempfile
import unittest
from pathlib import Path

from scripts import vllm_throughput_regression_diff as diff


class VllmThroughputRegressionDiffTest(unittest.TestCase):
	def write_json(self, root: Path, name: str, obj: dict) -> Path:
		path = root / name
		path.write_text(json.dumps(obj), encoding="utf-8")
		return(path)

	def test_prompt_tokens_parse_from_reference_shape(self) -> None:
		self.assertEqual(diff.prompt_tokens_from_shape("concurrency_sweep_15_prompt_tokens_32_output_tokens", 64), 960)
		self.assertIsNone(diff.prompt_tokens_from_shape("unknown", 64))

	def test_methodology_delta_is_classified(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			reference = self.write_json(root, "reference.json", {
				"benchmark_id": "ref",
				"prompt_shape": "concurrency_sweep_15_prompt_tokens_32_output_tokens",
				"request_max_tokens": 32,
				"concurrency_summaries": [
					{"concurrency": 64, "mean_aggregate_tps": 310.0, "rounds": 2, "successful_rounds": 2, "total_errors": 0}
				],
			})
			qualification = self.write_json(root, "qualification.json", {
				"format": "centaur-vllm-provider-qualification-v1",
				"provider_id": "local_vllm_pp2_tp2_c64",
				"api_mode": "openai_completions_fanout",
				"endpoint": "http://example.invalid/v1/completions",
				"stream_count": 64,
				"max_tokens": 32,
				"completion_tokens": 2048,
				"wall_seconds": 19.2,
				"measured_aggregate_tok_s": 106.6,
				"measured_per_stream_tok_s": 1.66,
				"status": "measured_out_of_tolerance",
				"error_count": 0,
			})
			matched = self.write_json(root, "matched.json", {
				"format": "ds4-vllm-openai-completions-fanout-v1",
				"prompt_mode": "distinct_mixed_length_no_prefix_cache_hit",
				"max_tokens": 32,
				"summaries": [
					{
						"concurrency": 64,
						"mean_aggregate_tps": 105.7,
						"total_prompt_tokens": 7114,
						"total_completion_tokens": 2048,
						"total_errors": 0,
						"successful_rounds": 1,
					}
				],
			})
			class Args:
				pass
			args = Args()
			args.reference_sweep = str(reference)
			args.qualification = str(qualification)
			args.matched_workload = str(matched)
			args.concurrency = 64
			args.matched_tolerance = 0.05
			args.regression_threshold = 0.25
			obj = diff.build_diff(args)
		self.assertEqual(obj["verdict_kind"], "methodology_artifact")
		self.assertTrue(obj["should_route_centaur_with_live_qualification"])
		self.assertAlmostEqual(obj["production_relevant_tok_s"], 106.6)
		self.assertGreater(obj["methodology_delta"]["matched_vs_reference_prompt_token_ratio"], 7.0)


if __name__ == "__main__":
	unittest.main()
