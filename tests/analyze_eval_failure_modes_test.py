import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts import analyze_eval_failure_modes as analysis


class AnalyzeEvalFailureModesTest(unittest.TestCase):
	def test_classifies_failures_from_run_outputs(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			jsonl = root / "run.jsonl"
			stdout = root / "run.stdout.txt.gz"
			out = root / "analysis.json"
			rows = [
				_question(1, "PASSED", "GPQA Diamond", "Physics", "B", "B", 2, True),
				_question(2, "FAILED", "AIME2025", "Combinatorics", "42", "7", 5, False),
				_question(3, "FAILED", "AIME2025", "Algebra", "10", "?", 4, False),
				_question(4, "FAILED", "SuperGPQA", "Law", "A", "B", 3, False),
				_summary(),
			]
			jsonl.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
			with gzip.open(stdout, "wt", encoding="utf-8") as f:
				f.write(
					"#   state      prompt      gen    total given    correct  test\n"
					"  1 PASSED         10        2       12 B        B        GPQA Diamond/case-1\n"
					"  2 FAILED         10        5       15 7        42       AIME2025/case-2\n"
					"  3 FAILED         10        4       14 ?        10       AIME2025/case-3\n"
					"  4 FAILED         10        3       13 B        A        SuperGPQA/case-4\n"
				)
			rc = analysis.main([
				"--jsonl", str(jsonl),
				"--stdout", str(stdout),
				"--out", str(out),
				"--run-id", "unit-run",
				"--max-tokens", "5",
			])
			self.assertEqual(rc, 0)
			result = json.loads(out.read_text(encoding="utf-8"))
			self.assertEqual(result["failed"], 3)
			self.assertEqual(_count(result, "truncation"), 1)
			self.assertEqual(_count(result, "format_error"), 1)
			self.assertEqual(_count(result, "wrong_answer"), 1)
			self.assertEqual(result["largest_failure_class"]["count"], 1)
			self.assertEqual(result["domain_breakdown"][0]["failed"], 1)
			self.assertTrue(any(item["stdout_report_line"] for item in result["failures"]))


def _question(index: int, status: str, source: str, domain: str, expected: str, observed: str, tokens: int, passed: bool) -> dict[str, object]:
	return {
		"format": "pipeline-quality-regression-v1",
		"record_type": "question",
		"run_id": "unit-run",
		"case_index": index,
		"case_id": f"case-{index}",
		"source": source,
		"domain": domain,
		"expected_answer": expected,
		"observed_answer": observed,
		"generated_tokens": tokens,
		"generated_text": "I can solve this.</think>\nAnswer: " + observed,
		"elapsed_sec": 1.0,
		"passed": passed,
		"ds4_eval_status": status,
	}


def _summary() -> dict[str, object]:
	return {
		"format": "pipeline-quality-regression-v1",
		"record_type": "summary",
		"run_id": "unit-run",
		"question_count": 4,
		"passed": 1,
		"failed": 3,
		"aggregate_output_tokens_per_s": 3.5,
	}


def _count(result: dict[str, object], failure_class: str) -> int:
	for item in result["failure_class_breakdown"]:
		if item["failure_class"] == failure_class:
			return int(item["count"])
	return 0


if __name__ == "__main__":
	unittest.main()
