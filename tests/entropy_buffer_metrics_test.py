import json
import os
import unittest

from scripts import entropy_buffer_lib as lib
from scripts import entropy_buffer_metrics as metrics
from scripts import entropy_buffer_recommend as recommend


def _repo_root() -> str:
    return(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))


class EntropyBufferMetricsTest(unittest.TestCase):
    def test_canonicalize_extracts_numeric_answer_and_judge_model(self) -> None:
        c = lib.canonicalize_record({
            "type": "task_run",
            "task_id": "math.add.999",
            "task_family": "math",
            "prompt_template_id": "plain.v1",
            "prompt": "Add 1+1",
            "output": "2",
        })
        self.assertEqual(c.rtype, "task_run")
        self.assertEqual(c.answer, "2")

        j = lib.canonicalize_record({
            "schema": "ds4_pairwise_judge_record_v1",
            "pair_id": "pair.test.001",
            "judge_model": "judge.vX",
            "model_a": "mA",
            "model_b": "mB",
            "winner": "A",
            "parse_valid": True,
        })
        self.assertEqual(j.rtype, "judge_pair")
        self.assertEqual(j.judge_id, "judge.vX")

    def test_metrics_from_mini_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        self.assertEqual(report.totals["records_total"], 12)
        self.assertEqual(report.totals["task_run_records"], 6)
        self.assertEqual(report.totals["judge_pair_records"], 5)
        self.assertEqual(report.totals["unknown_records"], 0)

        self.assertEqual(report.diversity["task_id"]["unique"], 5)
        self.assertEqual(report.diversity["task_family"]["unique"], 4)
        self.assertEqual(report.diversity["prompt_template_id"]["unique"], 4)
        self.assertEqual(report.diversity["task_family_template_pair"]["unique"], 4)
        self.assertEqual(report.diversity["model_id"]["unique"], 3)
        self.assertEqual(report.diversity["answer"]["unique"], 3)

        self.assertEqual(report.tokens["prompt_words_total"], 61)
        self.assertEqual(report.tokens["output_words_total"], 19)
        self.assertEqual(report.tokens["input_tokens"]["count"], 6)
        self.assertEqual(report.tokens["output_tokens"]["count"], 6)
        self.assertEqual(report.tokens["wall_ms"]["count"], 6)

        self.assertAlmostEqual(report.duplicates["output_norm_dup_rate"], 0.0)
        self.assertAlmostEqual(report.duplicates["prompt_norm_dup_rate"], (1.0 / 6.0))
        self.assertAlmostEqual(report.duplicates["answer_dup_rate"], 0.25)
        self.assertEqual(report.duplicates["task_template_groups_ge2"], 1)

        self.assertEqual(report.judge["label_counts"]["a"], 3)
        self.assertEqual(report.judge["label_counts"]["tie"], 1)
        self.assertEqual(report.judge["label_counts"]["invalid"], 1)
        self.assertAlmostEqual(report.judge["disagreement_rate"], 0.25)
        self.assertAlmostEqual(report.judge["disagreement_rate_decided_ab"], 0.0)
        self.assertEqual(report.judge["decided_count_ab"], 3)
        self.assertAlmostEqual(report.judge["decided_rate_ab"], 0.60)
        self.assertAlmostEqual(report.judge["label_balance_ab"], 0.0)
        self.assertAlmostEqual(report.judge["label_imbalance_ab"], 1.0)

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

        top = recommend._select(scored, history, limit=10, max_per_family=0, max_per_template=0, avoid_seen_task_id=True)
        self.assertGreaterEqual(len(top), 1)
        self.assertFalse(any(c.task_id == "math.add.001" and c.prompt_template_id == "cot.v2" for c in top))

    def test_useful_novelty_flags_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_flags_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        self.assertEqual(report.totals["task_run_records"], 2)
        self.assertEqual(report.useful_novelty["flagged_task_runs"], 2)
        flags = report.useful_novelty.get("flag_counts", {})
        self.assertGreaterEqual(flags.get("echo_prompt_overlap_ge_0.90", 0), 1)
        self.assertGreaterEqual(flags.get("line_repetition_ge_6", 0), 1)

    def test_recommendations_penalize_noisy_templates(self) -> None:
        root = _repo_root()
        hist_path = os.path.join(root, "fixtures", "entropy-buffer", "history_noise_mini.jsonl")
        cand_path = os.path.join(root, "fixtures", "entropy-buffer", "candidates_noise_mini.jsonl")
        history = lib.load_jsonl([hist_path])
        candidates = lib.load_jsonl([cand_path])

        scored = recommend._score(history, candidates)
        top = recommend._select(scored, history, limit=1, max_per_family=0, max_per_template=0, avoid_seen_task_id=False)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].prompt_template_id, "clean.v1")


if __name__ == "__main__":
    unittest.main()
