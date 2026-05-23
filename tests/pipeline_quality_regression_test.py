import io
import json
import http.server
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import pipeline_quality_regression as quality
from scripts import compare_pipeline_quality_runs as compare
from scripts import pipeline_throughput_truth as truth


DS4_EVAL_MINI = r'''
typedef struct {
    const char *source;
    const char *id;
    const char *domain;
    const char *title;
    const char *question;
    const char *choice[10];
    const char *answer;
} eval_case;

static const eval_case eval_cases[] = {
    {
        .source = "GPQA Diamond",
        .id = "mc-1",
        .domain = "Physics",
        .title = "choice",
        .question = "Pick the second letter.",
        .choice[0] = "alpha",
        .choice[1] = "beta",
        .answer = "B",
    },
    {
        .source = "AIME2025",
        .id = "int-1",
        .domain = "Math",
        .title = "integer",
        .question = "What is 0042?",
        .answer = "42",
    },
    {
        .source = "COMPSEC",
        .id = "comp-1",
        .domain = "C",
        .title = "line",
        .question = "Find the line.",
        .answer = "10-14",
    },
};
'''


RUNNER = """#!/usr/bin/env python3
import json
import pathlib
import sys
prompt = pathlib.Path(sys.argv[1]).read_text()
if "Pick the second letter" in prompt:
\ttext = "Reasoning done. Answer: B"
\ttokens = [101, 202]
elif "What is 0042" in prompt:
\ttext = "The value is clear. Answer: 42"
\ttokens = [303, 404, 505]
elif "Find the line" in prompt:
\ttext = "The dereference becomes unsafe. Answer: line 12"
\ttokens = [606]
elif "Hidden recall code" in prompt:
\ttext = "Answer: LANE-D-RECALL-CODE-7429"
\ttokens = [707, 808]
else:
\ttext = "Answer: ?"
\ttokens = [0]
print(json.dumps({"text": text, "token_ids": tokens, "elapsed_sec": 0.5}))
"""


DS4_EVAL_TRACE = """# ds4-eval trace
started_unix: 1
model: ds4flash.gguf
backend: cuda
ctx: 512
max_tokens: 32
questions: 2
temperature: 0
top_p: 1
min_p: 0.05
seed: 1

===== CASE 1/2 GPQA Diamond/mc-1 =====
timestamp_unix: 2
source: GPQA Diamond
id: mc-1
domain: Physics
title: choice
status: PASSED
picked: B
expected: B
prompt_tokens: 10
generated_tokens: 2
elapsed_sec: 0.500
choices:
  A. alpha
  B. beta
MODEL_OUTPUT_BEGIN bytes=9
Answer: B
MODEL_OUTPUT_END

===== CASE 2/2 COMPSEC/comp-1 =====
timestamp_unix: 3
source: COMPSEC
id: comp-1
domain: C
title: line
status: FAILED
picked: 9
expected: 10-14
prompt_tokens: 20
generated_tokens: 3
elapsed_sec: 1.500
MODEL_OUTPUT_BEGIN bytes=14
Answer: line 9
MODEL_OUTPUT_END

===== SUMMARY =====
passed: 1
failed: 1
total: 2
"""


class PipelineQualityRegressionTest(unittest.TestCase):
	def test_extracts_cases_from_ds4_eval_initializer(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			path = Path(d) / "ds4_eval.c"
			path.write_text(DS4_EVAL_MINI, encoding="utf-8")
			cases = quality.load_eval_cases(path)
		self.assertEqual([case.case_id for case in cases], ["mc-1", "int-1", "comp-1"])
		self.assertEqual(cases[0].choices, ("alpha", "beta"))
		self.assertIn("Answer: <letter>", quality.build_question_prompt(cases[0]))
		self.assertIn("Answer: <integer>", quality.build_question_prompt(cases[1]))
		self.assertIn("line number", quality.build_question_prompt(cases[2]))

	def test_grader_matches_ds4_eval_answer_rules(self) -> None:
		mc = quality.EvalCase("GPQA Diamond", "mc", "d", "t", "q", ("a", "b", "c"), "B")
		integer = quality.EvalCase("AIME2025", "int", "d", "t", "q", (), "0042")
		comp = quality.EvalCase("COMPSEC", "comp", "d", "t", "q", (), "10-14")
		self.assertEqual(quality.pick_answer(mc, "analysis\nAnswer: B"), "B")
		self.assertEqual(quality.pick_answer(mc, "Question choices: A. wrong B. right\nI first compare A and B.\nAnswer: B"), "B")
		self.assertTrue(quality.answer_matches(mc, "B", "Answer: B"))
		self.assertEqual(quality.pick_answer(integer, "work 1 2 Answer: 00042"), "42")
		self.assertTrue(quality.answer_matches(integer, "42", "Answer: 42"))
		self.assertEqual(quality.pick_answer(comp, "details\nAnswer: line 12"), "12")
		self.assertTrue(quality.answer_matches(comp, "12", "Answer: line 12"))
		self.assertFalse(quality.answer_matches(comp, "9", "Answer: line 9"))

	def test_command_runner_writes_quality_and_throughput_records(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			source = root / "ds4_eval.c"
			runner = root / "runner.py"
			out = root / "quality.jsonl"
			summary = root / "summary.json"
			source.write_text(DS4_EVAL_MINI, encoding="utf-8")
			runner.write_text(RUNNER, encoding="utf-8")
			with redirect_stdout(io.StringIO()):
				rc = quality.main([
					"--ds4-eval-source", str(source),
					"--command", f"python3 {runner} {{prompt_file}}",
					"--questions", "3",
					"--max-tokens", "8",
					"--run-id", "unit-run",
					"--runner-id", "unit-runner",
					"--backend-mode", "pp1",
					"--include-long-context",
					"--out", str(out),
					"--summary-out", str(summary),
				])
			self.assertEqual(rc, 0)
			rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
			question_rows = [row for row in rows if row["record_type"] == "question"]
			self.assertEqual(len(question_rows), 4)
			self.assertTrue(all(row["passed"] for row in question_rows))
			self.assertTrue(all(row["answer_marker_present"] for row in question_rows))
			self.assertTrue(all(row["length_capped"] is False for row in question_rows))
			self.assertEqual(rows[-1]["passed"], 4)
			self.assertEqual(
				[(item["source"], item["domain"], item["passed"], item["question_count"]) for item in rows[-1]["domain_breakdown"]],
				[("AIME2025", "Math", 1, 1), ("COMPSEC", "C", 1, 1), ("GPQA Diamond", "Physics", 1, 1), ("LONG_CONTEXT_RECALL", "Recall", 1, 1)],
			)
			throughput = truth.summarize(out)
			self.assertEqual(throughput["format"], "pipeline-throughput-truth-v1")
			self.assertEqual(throughput["question_count"], 4)
			self.assertGreater(throughput["aggregate_output_tokens_per_s"], 0.0)
			self.assertEqual(throughput["domain_breakdown"][0]["source"], "AIME2025")

	def test_openai_chat_runner_uses_completion_usage_and_trace_output(self) -> None:
		class Handler(http.server.BaseHTTPRequestHandler):
			def do_POST(self) -> None:
				length = int(self.headers.get("content-length", "0"))
				payload = json.loads(self.rfile.read(length).decode("utf-8"))
				self.server.requests.append(payload)  # type: ignore[attr-defined]
				body = json.dumps({
					"choices": [{"message": {"content": "Reasoning done.\nAnswer: B"}}],
					"usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
				}).encode("utf-8")
				self.send_response(200)
				self.send_header("content-type", "application/json")
				self.send_header("content-length", str(len(body)))
				self.end_headers()
				self.wfile.write(body)

			def log_message(self, _fmt: str, *_args: object) -> None:
				return

		server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
		server.requests = []  # type: ignore[attr-defined]
		thread = threading.Thread(target=server.serve_forever)
		thread.daemon = True
		thread.start()
		try:
			with tempfile.TemporaryDirectory() as d:
				root = Path(d)
				source = root / "ds4_eval.c"
				out = root / "quality.jsonl"
				trace = root / "quality.trace.txt"
				source.write_text(DS4_EVAL_MINI, encoding="utf-8")
				with redirect_stdout(io.StringIO()):
					rc = quality.main([
						"--ds4-eval-source", str(source),
						"--openai-chat-url", f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
						"--openai-model", "unit-model",
						"--questions", "1",
						"--max-tokens", "8",
						"--run-id", "openai-unit",
						"--runner-id", "unit-vllm",
						"--backend-mode", "vllm",
						"--out", str(out),
						"--trace-out", str(trace),
					])
				self.assertEqual(rc, 0)
				rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
				self.assertTrue(rows[0]["passed"])
				self.assertEqual(rows[0]["generated_tokens"], 7)
				self.assertEqual(rows[0]["coordinator"]["kind"], "openai_chat")
				self.assertEqual(rows[0]["openai_usage"]["completion_tokens"], 7)
				self.assertIn("MODEL_OUTPUT_BEGIN", trace.read_text(encoding="utf-8"))
				self.assertEqual(server.requests[0]["model"], "unit-model")  # type: ignore[attr-defined]
				self.assertEqual(server.requests[0]["seed"], 1)  # type: ignore[attr-defined]
		finally:
			server.shutdown()
			server.server_close()
			thread.join(timeout=5)

	def test_baseline_delta_marks_token_divergence(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			baseline = root / "baseline.jsonl"
			baseline.write_text(json.dumps({
				"format": quality.FORMAT,
				"record_type": "question",
				"case_id": "mc-1",
				"passed": True,
				"observed_answer": "B",
				"token_ids": [1, 2, 3],
			}) + "\n", encoding="utf-8")
			record = {
				"case_id": "mc-1",
				"passed": True,
				"observed_answer": "B",
				"token_ids": [1, 2, 4],
			}
			delta = quality.baseline_delta(record, quality.load_baseline(baseline))
		self.assertIsNotNone(delta)
		self.assertEqual(delta["delta_status"], "token_divergence")
		self.assertFalse(delta["token_ids_match"])

	def test_imports_ds4_eval_trace_records(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			trace = root / "ds4_eval.trace"
			out = root / "quality.jsonl"
			trace.write_text(DS4_EVAL_TRACE, encoding="utf-8")
			with redirect_stdout(io.StringIO()):
				rc = quality.main([
					"--ds4-eval-trace", str(trace),
					"--run-id", "trace-run",
					"--runner-id", "spark0-ds4-eval",
					"--backend-mode", "pp1",
					"--out", str(out),
				])
			self.assertEqual(rc, 0)
			rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
			self.assertEqual(rows[-1]["passed"], 1)
			self.assertEqual(rows[-1]["failed"], 1)
			self.assertEqual(rows[-1]["aggregate_output_tokens_per_s"], 2.5)
			self.assertEqual(rows[-1]["trace_started_unix"], 1)
			self.assertEqual(rows[-1]["startup_elapsed_sec"], 1)
			self.assertEqual(rows[-1]["first_case_started_unix"], 2)
			self.assertEqual(rows[-1]["last_case_started_unix"], 3)
			self.assertEqual(rows[-1]["last_case_completed_unix"], 4.5)
			self.assertEqual(rows[-1]["trace_wall_elapsed_sec"], 3.5)
			self.assertEqual(
				[(item["source"], item["domain"], item["passed"], item["failed"]) for item in rows[-1]["domain_breakdown"]],
				[("COMPSEC", "C", 0, 1), ("GPQA Diamond", "Physics", 1, 0)],
			)
			self.assertEqual(rows[0]["question_kind"], "multiple_choice")
			self.assertEqual(rows[1]["question_kind"], "compsec")
			self.assertEqual(rows[0]["generated_text"], "Answer: B")
			self.assertTrue(rows[0]["answer_marker_present"])
			self.assertEqual(rows[0]["max_tokens"], 32)

	def test_compares_quality_runs_with_mcnemar_verdict(self) -> None:
		with tempfile.TemporaryDirectory() as d:
			root = Path(d)
			baseline = root / "baseline.jsonl"
			candidate = root / "candidate.jsonl"
			out = root / "comparison.json"
			md = root / "comparison.md"
			base_rows = [
				{"record_type": "question", "case_id": "a", "case_index": 1, "source": "S", "domain": "D", "passed": True, "observed_answer": "A", "expected_answer": "A", "generated_tokens": 3, "generated_text": "Answer: A"},
				{"record_type": "question", "case_id": "b", "case_index": 2, "source": "S", "domain": "D", "passed": True, "observed_answer": "B", "expected_answer": "B", "generated_tokens": 3, "generated_text": "Answer: B"},
				{"record_type": "summary", "run_id": "base"},
			]
			cand_rows = [
				{"record_type": "question", "case_id": "a", "case_index": 1, "source": "S", "domain": "D", "passed": True, "observed_answer": "A", "expected_answer": "A", "generated_tokens": 3, "generated_text": "Answer: A"},
				{"record_type": "question", "case_id": "b", "case_index": 2, "source": "S", "domain": "D", "passed": False, "observed_answer": "C", "expected_answer": "B", "generated_tokens": 16000, "generated_text": "thinking without final marker"},
				{"record_type": "summary", "run_id": "cand"},
			]
			baseline.write_text("".join(json.dumps(row) + "\n" for row in base_rows), encoding="utf-8")
			candidate.write_text("".join(json.dumps(row) + "\n" for row in cand_rows), encoding="utf-8")
			with redirect_stdout(io.StringIO()):
				rc = compare.main(["--baseline", str(baseline), "--candidate", str(candidate), "--out", str(out), "--markdown-out", str(md)])
			self.assertEqual(rc, 0)
			result = json.loads(out.read_text(encoding="utf-8"))
			self.assertEqual(result["baseline_only_pass"], 1)
			self.assertEqual(result["candidate_only_pass"], 0)
			self.assertEqual(result["discordant_cases"][0]["case_id"], "b")
			self.assertEqual(result["length_cap_summary"]["length_capped_count"], 1)
			self.assertEqual(result["length_cap_summary"]["length_capped_without_answer_marker"], 1)
			self.assertTrue(result["length_cap_summary"]["cap_altered_comparison_delta"])
			self.assertEqual(result["verdict"], "worse")
			self.assertIn("vLLM MXFP4 TP=2 ds4-eval Comparison", md.read_text(encoding="utf-8"))


if __name__ == "__main__":
	unittest.main()
