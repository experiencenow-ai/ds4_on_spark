from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "ds4_eval_api_runner.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("ds4_eval_api_runner", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Ds4EvalApiRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_runner()

    def test_repo_fixture_contains_92_eval_cases(self) -> None:
        cases = self.runner.parse_eval_cases(self.runner.DEFAULT_SOURCE_C)

        self.assertEqual(len(cases), 92)
        self.assertEqual(cases[0]["index"], 0)
        self.assertTrue(cases[0]["id"])
        self.assertTrue(cases[0]["question"])
        self.assertTrue(cases[0]["answer"])

    def test_grades_choice_integer_and_compsec_answers(self) -> None:
        got, ok = self.runner._grade_one({"choices": ["x", "y", "z"], "answer": "B"}, "Reasoning.\nAnswer: B")
        self.assertEqual(got, "B")
        self.assertTrue(ok)

        got, ok = self.runner._grade_one({"answer": "4"}, "Reasoning.\nAnswer: 04")
        self.assertEqual(got, "4")
        self.assertTrue(ok)

        got, ok = self.runner._grade_one({"source": "COMPSEC", "answer": "12,13,14"}, "Reasoning.\nAnswer: 12-13")
        self.assertEqual(got, "12-13")
        self.assertTrue(ok)

    def test_missing_final_answer_marker_fails_closed(self) -> None:
        got, ok = self.runner._grade_one({"choices": ["x", "y", "z"], "answer": "B"}, "Reasoning mentions answer choices A, B, and C.")

        self.assertEqual(got, "?")
        self.assertFalse(ok)

    def test_request_id_remap_preserves_eval_metadata(self) -> None:
        rows = [
            {
                "request_id": "old",
                "input": {"metadata": {"ds4_eval": {"index": 7, "answer": "C"}}},
            }
        ]

        remapped = self.runner._remap_request_ids(rows, "batch")
        by_id = self.runner._request_meta_by_id(remapped)

        self.assertEqual(remapped[0]["request_id"], "batch-000000")
        self.assertEqual(by_id["batch-000000"]["index"], 7)
        self.assertEqual(by_id["batch-000000"]["answer"], "C")
        self.assertEqual(rows[0]["request_id"], "old")

    def test_answer_line_reports_live_accuracy_and_throughput(self) -> None:
        record = {
            "elapsed_s": 10.0,
            "passed": True,
            "index": 3,
            "source": "AIME",
            "id": "x",
            "got": "42",
            "expected": "42",
            "completion_tokens": 100,
        }
        self.runner._attach_cumulative_stats(record, 2, 92, 1, 150)

        line = self.runner._answer_line(record)

        self.assertIn("002/092", line)
        self.assertIn("acc= 50.0%", line)
        self.assertIn("cum_tok/s=  15.00", line)
        self.assertIn("PASS", line)
        self.assertIn("answer_marker=no", line)
        self.assertEqual(record["cumulative_completion_tokens"], 150)
        self.assertEqual(record["cumulative_completion_tok_s"], 15.0)

    def test_collect_items_are_keyed_by_request_id(self) -> None:
        collect = {
            "results": [
                {"request": {"request_id": "r1"}, "result": {"output": {"text": "Answer: A"}}},
                {"result": {"request_id": "r2", "output": {"text": "Answer: B"}}},
            ]
        }

        items = self.runner._collect_items_by_request_id(collect)

        self.assertEqual(set(items), {"r1", "r2"})


if __name__ == "__main__":
    unittest.main()
