import unittest

from scripts import run_small_model_mtp_c1_benchmark as bench


class SmallModelMtpC1BenchmarkTest(unittest.TestCase):
    def test_centaur_workload_has_fifty_nontrivial_prompts(self) -> None:
        prompts = bench.centaur_prompts()
        self.assertEqual(len(prompts), 50)
        self.assertEqual(len({item["task_id"] for item in prompts}), 50)
        self.assertTrue(all(len(item["prompt"].split()) > 80 for item in prompts))

    def test_loader_failure_classification_blocks_throughput(self) -> None:
        kind, detail = bench.classify("missing tensor 'blk.64.ssm_conv1d.weight'", "", 1)
        self.assertEqual(kind, "checkpoint_missing_tensor")
        self.assertIn("blk.64", detail)

    def test_parses_mtp_acceptance(self) -> None:
        perf = bench.parse_perf("llama_perf_context_print: total time = 120.0 ms / 24 tokens\nds4: mtp timing drafted=8 committed=6", "")
        self.assertEqual(perf["total_tokens"], 24)
        self.assertEqual(perf["attempted_draft_tokens"], 8)
        self.assertEqual(perf["accepted_draft_tokens"], 6)
        self.assertAlmostEqual(perf["draft_acceptance_rate"], 0.75)


if __name__ == "__main__":
    unittest.main()
