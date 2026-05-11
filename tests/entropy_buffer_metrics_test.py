import json
import os
import unittest

from scripts import entropy_buffer_lib as lib
from scripts import entropy_buffer_metrics as metrics
from scripts import entropy_buffer_recommend as recommend


def _repo_root() -> str:
    return(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))


class EntropyBufferMetricsTest(unittest.TestCase):
    def test_metrics_from_mini_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        self.assertEqual(report.totals["records_total"], 11)
        self.assertEqual(report.totals["task_run_records"], 6)
        self.assertEqual(report.totals["judge_pair_records"], 4)
        self.assertEqual(report.totals["unknown_records"], 0)

        self.assertEqual(report.diversity["task_id"]["unique"], 5)
        self.assertEqual(report.diversity["task_family"]["unique"], 4)
        self.assertEqual(report.diversity["prompt_template_id"]["unique"], 4)
        self.assertEqual(report.diversity["task_family_template_pair"]["unique"], 4)
        self.assertEqual(report.diversity["model_id"]["unique"], 3)
        self.assertEqual(report.diversity["answer"]["unique"], 3)

        self.assertEqual(report.tokens["prompt_words_total"], 61)
        self.assertEqual(report.tokens["output_words_total"], 19)

        self.assertAlmostEqual(report.duplicates["output_norm_dup_rate"], 0.0)
        self.assertAlmostEqual(report.duplicates["prompt_norm_dup_rate"], (1.0 / 6.0))
        self.assertEqual(report.duplicates["task_template_groups_ge2"], 1)

        self.assertEqual(report.judge["label_counts"]["a"], 3)
        self.assertEqual(report.judge["label_counts"]["tie"], 1)
        self.assertAlmostEqual(report.judge["disagreement_rate"], 0.25)
        self.assertEqual(report.judge["decided_count_ab"], 3)
        self.assertAlmostEqual(report.judge["decided_rate_ab"], 0.75)
        self.assertAlmostEqual(report.judge["label_balance_ab"], 1.0)

        self.assertEqual(report.useful_novelty["flagged_task_runs"], 1)

    def test_recommendations_prioritize_unseen_pairs(self) -> None:
        root = _repo_root()
        hist_path = os.path.join(root, "fixtures", "entropy-buffer", "records_mini.jsonl")
        cand_path = os.path.join(root, "fixtures", "entropy-buffer", "candidates_mini.jsonl")
        history = lib.load_jsonl([hist_path])
        candidates = lib.load_jsonl([cand_path])

        scored = recommend._score(history, candidates)
        self.assertGreaterEqual(len(scored), 1)
        self.assertEqual(scored[0].seen_task_id, 0)
        self.assertIn(scored[0].task_family, ("code",))


if __name__ == "__main__":
    unittest.main()
