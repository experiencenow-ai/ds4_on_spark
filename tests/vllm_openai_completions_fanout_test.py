import unittest
import tempfile
from pathlib import Path

from scripts import benchmark_vllm_openai_completions_fanout as fanout


class VllmOpenAICompletionsFanoutTest(unittest.TestCase):
	def test_parse_ints_accepts_spaces_and_commas(self) -> None:
		self.assertEqual(fanout.parse_ints("1, 2 4"), [1, 2, 4])

	def test_parse_rounds(self) -> None:
		self.assertEqual(fanout.parse_rounds("1:5, 512:1"), {1: 5, 512: 1})

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

	def test_standard_artifact_uses_max_tokens_when_list_empty(self) -> None:
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
		args.concurrency = "1"
		args.max_tokens = 128
		args.max_tokens_list = ""
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
			"summaries": [{"concurrency": 1, "output_length": 128, "mean_aggregate_tps": 10.0, "mean_per_stream_tps": 10.0}],
			"rounds": [],
		}
		obj = fanout.build_standard_runtime_artifact(args, raw)
		self.assertEqual(obj["request_output_lengths"], [128])


if __name__ == "__main__":
	unittest.main()
