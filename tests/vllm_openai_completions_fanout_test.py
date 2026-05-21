import unittest

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

	def test_summarize_reports_mean_and_per_stream(self) -> None:
		rows = [
			{"aggregate_tps": 100.0, "requests_per_second": 10.0, "completion_tokens": 32, "prompt_tokens": 80, "errors": 0},
			{"aggregate_tps": 120.0, "requests_per_second": 12.0, "completion_tokens": 32, "prompt_tokens": 96, "errors": 0},
		]
		obj = fanout.summarize(4, rows)
		self.assertEqual(obj["successful_rounds"], 2)
		self.assertAlmostEqual(obj["mean_aggregate_tps"], 110.0)
		self.assertAlmostEqual(obj["mean_per_stream_tps"], 27.5)
		self.assertEqual(obj["total_completion_tokens"], 64)


if __name__ == "__main__":
	unittest.main()
