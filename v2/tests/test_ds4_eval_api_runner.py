from __future__ import annotations

import argparse
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

    def test_source_filter_selects_compsec17_cases(self) -> None:
        cases = self.runner.parse_eval_cases(self.runner.DEFAULT_SOURCE_C)

        filtered = self.runner._filter_cases(cases, ["COMPSEC"])

        self.assertEqual(len(filtered), 17)
        self.assertTrue(all(case["source"] == "COMPSEC" for case in filtered))
        self.assertEqual(filtered[0]["id"], "compsec-076")
        self.assertEqual(filtered[-1]["id"], "compsec-092")

    def test_request_payload_source_filter_selects_metadata_source(self) -> None:
        rows = [
            {
                "request_id": "a",
                "input": {"metadata": {"ds4_eval": {"source": "AIME2025"}}},
            },
            {
                "request_id": "b",
                "input": {"metadata": {"ds4_eval": {"source": "COMPSEC"}}},
            },
        ]

        filtered = self.runner._filter_request_payloads(rows, ["COMPSEC"])

        self.assertEqual([row["request_id"] for row in filtered], ["b"])

    def test_run_defaults_enable_thinking_with_bounded_budget(self) -> None:
        parser = self.runner._build_parser()
        args = parser.parse_args(["run", "--out-dir", "/tmp/ds4-eval-test"])

        self.assertTrue(args.enable_thinking)
        self.assertEqual(args.thinking_budget_tokens, 1024)

    def test_run_accepts_source_filter(self) -> None:
        parser = self.runner._build_parser()
        args = parser.parse_args(["run", "--out-dir", "/tmp/ds4-eval-test", "--source", "COMPSEC"])

        self.assertEqual(args.source, ["COMPSEC"])

    def test_run_can_disable_thinking_for_diagnostics(self) -> None:
        parser = self.runner._build_parser()
        args = parser.parse_args(["run", "--out-dir", "/tmp/ds4-eval-test", "--disable-thinking"])

        self.assertFalse(args.enable_thinking)

    def test_disabled_thinking_zeros_request_budget(self) -> None:
        args = argparse.Namespace(
            vllm_url="http://vllm",
            served_model="model",
            max_output_tokens=64,
            enable_thinking=False,
            chat_template_thinking_key="thinking",
            thinking_budget_tokens=1024,
            response_style="concise",
            temperature=0.0,
            model="profile",
        )
        case = {
            "id": "compsec-x",
            "question": "Find the bug.",
            "source": "COMPSEC",
            "domain": "kernel",
            "title": "case",
            "answer": "3",
            "choices": [],
        }
        original_render_prompt = self.runner.render_prompt
        self.runner.render_prompt = lambda *args, **kwargs: "rendered"
        try:
            payload = self.runner._eval_request_payload(args, 0, case)
        finally:
            self.runner.render_prompt = original_render_prompt

        self.assertEqual(payload["thinking_budget_tokens"], 0)
        self.assertEqual(payload["input"]["rendered_prompt"], "rendered")

    def test_render_prompt_sends_explicit_disabled_thinking_kwarg(self) -> None:
        calls = []
        original_post_json = self.runner._post_json

        def fake_post_json(base_url, path, payload):
            calls.append((base_url, path, payload))
            if path == "/v1/chat/completions/render":
                return {"token_ids": [1, 2, 3]}
            if path == "/detokenize":
                return {"prompt": "rendered"}
            raise AssertionError(path)

        self.runner._post_json = fake_post_json
        try:
            rendered = self.runner.render_prompt(
                "http://vllm",
                "qwen",
                "question",
                64,
                enable_thinking=False,
                thinking_key="enable_thinking",
            )
        finally:
            self.runner._post_json = original_post_json

        self.assertEqual(rendered, "rendered")
        self.assertEqual(calls[0][2]["chat_template_kwargs"], {"enable_thinking": False})

    def test_default_eval_prompt_keeps_official_contract(self) -> None:
        prompt = self.runner.build_question_prompt(
            {"question": "Pick one.", "choices": ["alpha", "beta"], "source": "X"}
        )

        self.assertIn("At the end", prompt)
        self.assertIn("Answer: <letter>", prompt)
        self.assertNotIn("Output exactly one line", prompt)

    def test_concise_eval_prompt_requests_short_reasoning(self) -> None:
        prompt = self.runner.build_question_prompt(
            {"question": "Pick one.", "choices": ["alpha", "beta"], "source": "X"},
            response_style="concise",
        )

        self.assertIn("at most three short sentences", prompt)
        self.assertIn("Answer: <letter>", prompt)

    def test_answer_only_eval_prompt_requests_single_line(self) -> None:
        prompt = self.runner.build_question_prompt(
            {"question": "Pick one.", "choices": ["alpha", "beta"], "source": "X"},
            response_style="answer_only",
        )

        self.assertIn("Output exactly one line", prompt)
        self.assertIn("Answer: <letter>", prompt)

    def test_official_eval_prompt_keeps_legacy_end_marker_contract(self) -> None:
        prompt = self.runner.build_question_prompt(
            {"question": "Pick one.", "choices": ["alpha", "beta"], "source": "X"},
            response_style="official",
        )

        self.assertIn("At the end", prompt)
        self.assertIn("Answer: <letter>", prompt)

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

    def test_multiple_choice_preserves_loose_answer_fallback(self) -> None:
        got, ok = self.runner._grade_one(
            {"choices": ["A", "B", "C", "D", "E", "F", "G", "H"], "answer": "F"},
            "</think>The answer is F. This answer is final; option H is tempting.",
        )

        self.assertEqual(got, "F")
        self.assertTrue(ok)

    def test_multiple_choice_prefers_high_confidence_phrase_fallback(self) -> None:
        got, ok = self.runner._grade_one(
            {"choices": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], "answer": "C"},
            "Choice C is plausible. A is wrong. J is a distractor.",
        )

        self.assertEqual(got, "C")
        self.assertTrue(ok)

    def test_multiple_choice_accepts_select_option_phrase(self) -> None:
        got, ok = self.runner._grade_one(
            {"choices": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], "answer": "J"},
            "The correct title is Shuowen Jiezi. Select the correct option: J.",
        )

        self.assertEqual(got, "J")
        self.assertTrue(ok)

    def test_multiple_choice_ignores_placeholder_answer_marker(self) -> None:
        got, ok = self.runner._grade_one(
            {"choices": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], "answer": "J"},
            'The requested format is "Answer: <letter>". Option J corresponds to the correct title. A is close but wrong.',
        )

        self.assertEqual(got, "J")
        self.assertTrue(ok)

    def test_multiple_choice_accepts_option_description_phrase(self) -> None:
        got, ok = self.runner._grade_one(
            {"choices": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], "answer": "C"},
            "C. a block of grass - This seems plausible. J. a bundle of sticks - no.",
        )

        self.assertEqual(got, "C")
        self.assertTrue(ok)

    def test_multiple_choice_answer_marker_beats_later_prose(self) -> None:
        got, ok = self.runner._grade_one(
            {"choices": ["A", "B", "C", "D", "E", "F", "G", "H"], "answer": "F"},
            "</think>Answer: F\nThis answer is final; option H is tempting.",
        )

        self.assertEqual(got, "F")
        self.assertTrue(ok)

    def test_integer_preserves_loose_answer_fallback(self) -> None:
        got, ok = self.runner._grade_one(
            {"source": "AIME2025", "answer": "82"},
            "</think>The answer is 082. This answer comes from AIME 2025.",
        )

        self.assertEqual(got, "82")
        self.assertTrue(ok)

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
