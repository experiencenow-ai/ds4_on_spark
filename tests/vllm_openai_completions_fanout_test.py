import unittest
import tempfile
from pathlib import Path

from scripts import benchmark_vllm_openai_completions_fanout as fanout


class VllmOpenAICompletionsFanoutTest(unittest.TestCase):
	def test_parse_ints_accepts_spaces_and_commas(self) -> None:
		self.assertEqual(fanout.parse_ints("1, 2 4"), [1, 2, 4])

	def test_parse_rounds(self) -> None:
		self.assertEqual(fanout.parse_rounds("1:5, 512:1"), {1: 5, 512: 1})

	def test_parse_choices(self) -> None:
		self.assertEqual(fanout.parse_choices("yes, no,,escalate"), ["yes", "no", "escalate"])

	def test_mixed_prompts_are_distinct(self) -> None:
		prompts = [fanout.mixed_prompt(i, 0) for i in range(8)]
		self.assertEqual(len(set(prompts)), 8)
		self.assertTrue(all(len(p) > 20 for p in prompts))

	def test_prompt_file_cycles_real_prompts(self) -> None:
		with tempfile.TemporaryDirectory() as tmp:
			path = Path(tmp) / "prompts.txt"
			path.write_text("alpha\n\nbeta\n", encoding="utf-8")
			prompts = fanout.load_prompts(str(path))
		self.assertEqual(prompts, ["alpha", "beta"])
		self.assertEqual(fanout.prompt_for(0, 0, prompts), "alpha")
		self.assertEqual(fanout.prompt_for(2, 1, prompts), "beta")

	def test_summarize_reports_mean_and_per_stream(self) -> None:
		rows = [
			{"concurrency": 4, "aggregate_tps": 100.0, "requests_per_second": 10.0, "completion_tokens": 32, "prompt_tokens": 80, "errors": 0},
			{"concurrency": 4, "aggregate_tps": 120.0, "requests_per_second": 12.0, "completion_tokens": 32, "prompt_tokens": 96, "errors": 0},
		]
		obj = fanout.summarize(4, 32, rows)
		self.assertEqual(obj["output_length"], 32)
		self.assertEqual(obj["successful_rounds"], 2)
		self.assertAlmostEqual(obj["mean_aggregate_tps"], 110.0)
		self.assertAlmostEqual(obj["mean_per_stream_tps"], 27.5)
		self.assertEqual(obj["total_completion_tokens"], 64)
		self.assertAlmostEqual(obj["mean_completion_tokens_per_request"], 8.0)

	def test_summarize_uses_request_count_when_present(self) -> None:
		rows = [
			{"concurrency": 4, "request_count": 100, "aggregate_tps": 100.0, "requests_per_second": 25.0, "completion_tokens": 300, "prompt_tokens": 800, "errors": 0},
		]
		obj = fanout.summarize(4, 32, rows)
		self.assertAlmostEqual(obj["mean_completion_tokens_per_request"], 3.0)

	def test_draft_acceptance_rate_uses_total_counters(self) -> None:
		deltas = {
			"vllm:spec_decode_num_accepted_tokens_total": 50.0,
			"vllm:spec_decode_num_accepted_tokens_per_pos_total": 50.0,
			"vllm:spec_decode_num_draft_tokens_total": 100.0,
		}
		self.assertAlmostEqual(fanout.draft_acceptance_rate(deltas), 0.5)

	def test_standard_artifact_hashes(self) -> None:
		class Args:
			pass
		args = Args()
		args.benchmark_id = "bench"
		args.provider_id = "provider"
		args.model_id = "model"
		args.model_family = "family"
		args.runtime_version = "runtime"
		args.quantization = "quant"
		args.hardware_fabric = "fabric"
		args.hardware_head_node = "head"
		args.hardware_launcher_node = "launcher"
		args.hardware_machine = "machine"
		args.hardware_worker_node = "worker"
		args.launch_command = "launch"
		args.endpoint = "http://127.0.0.1:8000/v1/completions"
		args.context_length = 10
		args.concurrency = "8 32"
		args.max_tokens_list = "32 128"
		args.prompt_source = "source"
		args.ignore_eos = True
		args.time_to_first_token_ms = 0.0
		args.time_to_first_token_source = "unit"
		args.prompt_processing_tokens_per_second = 0.0
		args.prompt_processing_tokens_per_second_source = "unit"
		args.memory_used_gib = 1.0
		args.note = []
		raw = {
			"created_utc": "2026-05-21T00:00:00Z",
			"prompt_source_sha256": "abc",
			"summaries": [{"concurrency": 32, "output_length": 128, "mean_aggregate_tps": 10.0, "mean_per_stream_tps": 0.3125}],
			"rounds": [],
		}
		obj = fanout.build_standard_runtime_artifact(args, raw)
		self.assertEqual(obj["format"], fanout.STANDARD_RUNTIME_FORMAT)
		self.assertEqual(obj["hardware"]["head_node"], "head")
		self.assertEqual(obj["hardware"]["worker_node"], "worker")
		self.assertEqual(obj["tokens_per_second"], 10.0)
		self.assertEqual(obj["artifact_sha256"], fanout.canonical_hash(obj))


if __name__ == "__main__":
	unittest.main()
