import json
import os
import unittest

from scripts import entropy_buffer_lib as lib
from scripts import entropy_buffer_canonicalize as canonicalize
from scripts import entropy_buffer_diff as diff
from scripts import entropy_buffer_filter as filt
from scripts import entropy_buffer_gaps as gaps
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
        self.assertEqual(c.answer_source, "extract")

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

    def test_canonicalize_tool_emits_item_id_and_instrumentation(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_canonicalize_mini.jsonl")
        records = lib.load_jsonl([path])
        out = canonicalize.canonicalize_records(records)

        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].get("type"), "task_run")
        self.assertEqual(out[0].get("answer"), "B")
        self.assertEqual(out[0].get("answer_source"), "extract")
        self.assertEqual(int(out[0].get("input_tokens", 0)), 12)
        self.assertEqual(int(out[0].get("output_tokens", 0)), 3)
        self.assertAlmostEqual(float(out[0].get("wall_ms", 0.0)), 1000.0)

        self.assertEqual(out[1].get("type"), "judge_pair")
        self.assertEqual(out[1].get("item_id"), "math.add.001|mcq.v1|a=m1|b=m2")
        toks = out[1].get("tokens") or {}
        lats = out[1].get("latency_ms") or {}
        self.assertEqual(int(toks.get("judge_in", 0)), 128)
        self.assertEqual(int(toks.get("judge_out", 0)), 64)
        self.assertAlmostEqual(float(lats.get("judge", 0.0)), 1500.0)

    def test_answer_extraction_accepts_answer_is_variants(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_answer_is_mini.jsonl")
        records = lib.load_jsonl([path])
        canon = [lib.canonicalize_record(x) for x in records]
        self.assertEqual(canon[0].answer, "B")
        self.assertEqual(canon[0].answer_source, "extract")
        self.assertEqual(canon[1].answer, "42")
        self.assertEqual(canon[1].answer_source, "extract")
        self.assertEqual(canon[2].answer, "")
        self.assertEqual(canon[2].answer_source, "missing")

    def test_metrics_from_mini_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        self.assertEqual(report.totals["records_total"], 12)
        self.assertEqual(report.totals["task_run_records"], 6)
        self.assertEqual(report.totals["judge_pair_records"], 5)
        self.assertEqual(report.totals["unknown_records"], 0)

        fc = report.totals.get("field_coverage") or {}
        tr = fc.get("task_run") or {}
        jp = fc.get("judge_pair") or {}
        self.assertEqual(int(tr.get("answer_present_task_runs", 0)), 4)
        self.assertAlmostEqual(float(tr.get("answer_present_task_run_rate", 0.0)), (4.0 / 6.0))
        self.assertEqual(int(jp.get("judge_id_present_judge_pairs", 0)), 4)
        self.assertEqual(int(jp.get("parse_valid_present_judge_pairs", 0)), 1)
        self.assertEqual(int(jp.get("task_family_present_judge_pairs", 0)), 4)
        self.assertEqual(int(jp.get("prompt_template_id_present_judge_pairs", 0)), 4)

        self.assertEqual(report.runs["run_id_unique"], 1)
        dup_top = report.runs.get("output_norm_dup_rate_by_run_id_top", [])
        self.assertGreaterEqual(len(dup_top), 1)
        self.assertEqual(dup_top[0].get("run_id"), "baseline-20260511-spark0")
        flagged_top = report.runs.get("flagged_task_run_rate_by_run_id_top", [])
        self.assertGreaterEqual(len(flagged_top), 1)
        self.assertEqual(flagged_top[0].get("run_id"), "baseline-20260511-spark0")
        self.assertAlmostEqual(float(flagged_top[0].get("flagged_task_run_rate", 0.0)), (1.0 / 6.0))

        self.assertEqual(report.diversity["task_id"]["unique"], 5)
        self.assertEqual(report.diversity["task_family"]["unique"], 4)
        self.assertEqual(report.diversity["prompt_template_id"]["unique"], 4)
        self.assertEqual(report.diversity["task_family_template_pair"]["unique"], 4)
        self.assertEqual(report.diversity["model_id"]["unique"], 3)
        self.assertEqual(report.diversity["answer"]["unique"], 3)
        self.assertIn("hhi", report.diversity["task_id"])
        self.assertIn("hhi", report.diversity["task_family"])

        self.assertEqual(report.tokens["prompt_words_total"], 61)
        self.assertEqual(report.tokens["output_words_total"], 19)
        self.assertEqual(report.tokens["input_tokens"]["count"], 6)
        self.assertEqual(report.tokens["output_tokens"]["count"], 6)
        self.assertEqual(report.tokens["wall_ms"]["count"], 6)
        self.assertEqual(int(report.tokens.get("input_tokens_present_task_runs", 0)), 6)
        self.assertAlmostEqual(float(report.tokens.get("input_tokens_present_task_run_rate", 0.0)), 1.0)
        self.assertEqual(int(report.tokens.get("output_tokens_present_task_runs", 0)), 6)
        self.assertAlmostEqual(float(report.tokens.get("output_tokens_present_task_run_rate", 0.0)), 1.0)
        self.assertEqual(int(report.tokens.get("wall_ms_present_task_runs", 0)), 6)
        self.assertAlmostEqual(float(report.tokens.get("wall_ms_present_task_run_rate", 0.0)), 1.0)

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
        self.assertEqual(int(report.judge.get("parse_valid_true", 0)), 0)
        self.assertEqual(int(report.judge.get("parse_valid_false", 0)), 1)
        self.assertAlmostEqual(float(report.judge.get("parse_valid_rate", 0.0)), 0.0)
        self.assertEqual(int((report.judge.get("judge_in_tokens") or {}).get("count", 0)), 0)
        self.assertEqual(int((report.judge.get("judge_out_tokens") or {}).get("count", 0)), 0)
        self.assertEqual(int((report.judge.get("judge_latency_ms") or {}).get("count", 0)), 0)
        self.assertAlmostEqual(float(report.judge.get("task_family_nonempty_judge_pair_rate", 0.0)), (4.0 / 5.0))
        self.assertAlmostEqual(float(report.judge.get("prompt_template_id_nonempty_judge_pair_rate", 0.0)), (4.0 / 5.0))
        self.assertAlmostEqual(float(report.judge.get("task_family_template_pair_nonempty_judge_pair_rate", 0.0)), (4.0 / 5.0))

        by_judge = report.judge.get("judge_id_summary") or {}
        self.assertIn("judge.v1", by_judge)
        self.assertIn("judge.v2", by_judge)
        self.assertEqual(int((by_judge.get("judge.v1") or {}).get("count", 0)), 2)
        self.assertEqual(int((by_judge.get("judge.v2") or {}).get("count", 0)), 2)
        imb_top = report.judge.get("judge_id_imbalance_ab_top") or []
        self.assertGreaterEqual(len(imb_top), 2)
        self.assertEqual(imb_top[0].get("judge_id"), "judge.v1")

        self.assertAlmostEqual(float(report.reuse.get("buffer_id_nonempty_task_run_rate", 0.0)), 1.0)
        self.assertAlmostEqual(float(report.reuse.get("buffer_item_id_nonempty_task_run_rate", 0.0)), 1.0)

        self.assertEqual(report.useful_novelty["flagged_task_runs"], 1)

        useful = report.useful_coverage
        self.assertEqual(int(useful.get("clean_task_run_records", 0)), 5)
        self.assertAlmostEqual(float(useful.get("clean_task_run_rate", 0.0)), (5.0 / 6.0))
        flagged_model_top = report.useful_novelty.get("flagged_rate_by_model_id_top", [])
        self.assertGreaterEqual(len(flagged_model_top), 1)
        self.assertEqual(flagged_model_top[0].get("model_id"), "bad-model")
        self.assertAlmostEqual(float(flagged_model_top[0].get("flagged_rate", 0.0)), 1.0)

        dup_model_top = report.duplicates.get("output_norm_dup_rate_by_model_id_top", [])
        self.assertGreaterEqual(len(dup_model_top), 1)
        by_model = {str(js.get("model_id", "")): js for js in dup_model_top}
        self.assertIn("dsv4-flash", by_model)
        self.assertAlmostEqual(float(by_model["dsv4-flash"].get("dup_rate", 1.0)), 0.0)

    def test_metrics_extract_task_run_nested_tokens_and_latency(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_task_run_nested_tokens_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        self.assertEqual(report.totals["task_run_records"], 2)
        self.assertEqual((report.tokens.get("input_tokens") or {}).get("count", 0), 2)
        self.assertEqual((report.tokens.get("output_tokens") or {}).get("count", 0), 2)
        self.assertEqual((report.tokens.get("wall_ms") or {}).get("count", 0), 2)
        self.assertEqual((report.tokens.get("ms_per_output_token") or {}).get("count", 0), 2)
        self.assertAlmostEqual(float((report.tokens.get("ms_per_output_token") or {}).get("mean", 0.0)), (58.3333333333), places=4)
        self.assertAlmostEqual(float((report.tokens.get("output_tok_per_s") or {}).get("mean", 0.0)), (17.5), places=4)

    def test_answer_letter_diversity_from_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_answer_letter_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        ans = report.diversity.get("answer") or {}
        letter = ans.get("letter") or {}
        self.assertEqual(int(letter.get("unique", 0)), 3)
        self.assertEqual(int(letter.get("nonempty_task_runs", 0)), 3)
        self.assertAlmostEqual(float(letter.get("entropy_norm", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(letter.get("effective_num", 0.0)), 3.0, places=6)
        self.assertAlmostEqual(float(letter.get("hhi", 0.0)), (1.0 / 3.0), places=6)

    def test_answer_letter_variation_by_task_template_from_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_answer_letter_variation_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        ans = report.diversity.get("answer") or {}
        var = ans.get("letter_variation_by_task_id_template_pair") or {}
        self.assertEqual(int(var.get("min_count", 0) or 0), 2)
        self.assertEqual(int(var.get("groups_ge_min_count", 0) or 0), 2)
        self.assertAlmostEqual(float(var.get("entropy_norm_max", 0.0) or 0.0), 0.9182958340544896, places=6)
        self.assertAlmostEqual(float(var.get("entropy_norm_mean", 0.0) or 0.0), 0.4591479170272448, places=6)
        self.assertEqual(int(var.get("unique_max", 0) or 0), 2)

        top = var.get("top") or []
        self.assertGreaterEqual(len(top), 1)
        self.assertEqual(top[0].get("task_id_template_pair"), "mcq.1|mcq.v1")

    def test_token_slice_entropy_lists_exist(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_token_slices_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        slices = report.tokens.get("slices", {})
        by_tmpl = slices.get("output_word_by_prompt_template_id", {})
        low = by_tmpl.get("low_entropy_norm_top", [])
        self.assertGreaterEqual(len(low), 1)
        self.assertEqual(low[0].get("prompt_template_id"), "low.v1")
        self.assertAlmostEqual(float(low[0].get("entropy_norm", 1.0)), 0.0)

        by_model = slices.get("output_word_by_model_id", {})
        lowm = by_model.get("low_entropy_norm_top", [])
        self.assertGreaterEqual(len(lowm), 1)
        self.assertEqual(lowm[0].get("model_id"), "m_low")

    def test_conditional_entropy_stats_from_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_conditional_entropy_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        cond = report.diversity.get("conditional") or {}
        pt_given_family = cond.get("prompt_template_id_given_task_family") or {}
        self.assertAlmostEqual(float(pt_given_family.get("conditional_entropy_bits", 0.0)), 0.5, places=6)
        self.assertAlmostEqual(float(pt_given_family.get("conditional_entropy_norm", 0.0)), 0.5, places=6)
        self.assertAlmostEqual(float(pt_given_family.get("mutual_info_bits", 0.0)), 0.31127812445913283, places=6)
        self.assertAlmostEqual(float(pt_given_family.get("mutual_info_norm", 0.0)), 0.3836885465963443, places=6)

    def test_conditional_entropy_extra_axes_from_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_conditional_axes_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        cond = report.diversity.get("conditional") or {}
        model_given_template = cond.get("model_id_given_prompt_template_id") or {}
        self.assertAlmostEqual(float(model_given_template.get("conditional_entropy_bits", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(model_given_template.get("conditional_entropy_norm", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(model_given_template.get("mutual_info_bits", 0.0)), 0.0, places=6)

        answer_given_family = cond.get("answer_given_task_family") or {}
        self.assertAlmostEqual(float(answer_given_family.get("conditional_entropy_bits", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(answer_given_family.get("conditional_entropy_norm", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(answer_given_family.get("mutual_info_bits", 0.0)), 0.0, places=6)

    def test_judge_budget_metrics_from_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_judge_budget_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        self.assertEqual(report.totals["judge_pair_records"], 2)
        self.assertEqual(int(report.judge.get("parse_valid_true", 0)), 2)
        self.assertEqual(int(report.judge.get("parse_valid_false", 0)), 0)
        self.assertAlmostEqual(float(report.judge.get("parse_valid_rate", 0.0)), 1.0)
        self.assertAlmostEqual(float(report.judge.get("label_entropy_bits", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(report.judge.get("label_entropy_norm", 0.0)), 1.0, places=6)
        self.assertAlmostEqual(float(report.judge.get("label_effective_num", 0.0)), 2.0, places=6)
        self.assertAlmostEqual(float(report.judge.get("label_hhi", 0.0)), 0.5, places=6)
        self.assertEqual(int((report.judge.get("judge_in_tokens") or {}).get("count", 0)), 2)
        self.assertEqual(int((report.judge.get("judge_out_tokens") or {}).get("count", 0)), 2)
        self.assertEqual(int((report.judge.get("judge_latency_ms") or {}).get("count", 0)), 2)
        self.assertGreaterEqual(float(report.judge.get("judge_out_budget_le_target_rate", 0.0)), 0.5)

    def test_judge_disagreement_vs_majority_from_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_judge_majority_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        top = report.judge.get("judge_id_disagreement_vs_majority_rate_top", [])
        self.assertGreaterEqual(len(top), 1)
        self.assertEqual(top[0].get("judge_id"), "judge.v3")
        self.assertAlmostEqual(float(top[0].get("disagreement_vs_majority_rate", 0.0)), 1.0)
        self.assertEqual(int(top[0].get("majority_item_count", 0) or 0), 1)

        top_ab = report.judge.get("judge_id_disagreement_vs_majority_rate_decided_ab_top", [])
        self.assertGreaterEqual(len(top_ab), 1)
        self.assertEqual(top_ab[0].get("judge_id"), "judge.v3")
        self.assertAlmostEqual(float(top_ab[0].get("disagreement_vs_majority_rate_decided_ab", 0.0)), 1.0)

        summ = report.judge.get("judge_id_summary", {}) or {}
        j3 = summ.get("judge.v3") or {}
        self.assertEqual(int(j3.get("majority_item_count", 0) or 0), 1)
        self.assertAlmostEqual(float(j3.get("disagreement_vs_majority_rate", 0.0)), 1.0)
        self.assertEqual(int(j3.get("majority_item_count_decided_ab", 0) or 0), 1)
        self.assertAlmostEqual(float(j3.get("disagreement_vs_majority_rate_decided_ab", 0.0)), 1.0)
        self.assertGreaterEqual(float(report.judge.get("judge_id_disagreement_vs_majority_rate_max", 0.0)), 1.0)
        self.assertGreaterEqual(float(report.judge.get("judge_id_disagreement_vs_majority_rate_decided_ab_max", 0.0)), 1.0)

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

        predicted = recommend._predict(history, top)
        self.assertIn("coverage_before", predicted)
        self.assertIn("coverage_after", predicted)
        self.assertIn("coverage_delta", predicted)
        self.assertGreaterEqual(int((predicted.get("coverage_after") or {}).get("task_family", {}).get("unique", 0)), int((predicted.get("coverage_before") or {}).get("task_family", {}).get("unique", 0)))
        self.assertIsInstance(float(predicted.get("selected_history_noise_rate_mean", 0.0)), float)
        self.assertIsInstance(float(predicted.get("selected_expected_clean_rate_mean", 0.0)), float)
        self.assertIsInstance(float(predicted.get("selected_history_dup_rate_mean", 0.0)), float)
        self.assertIsInstance(float(predicted.get("selected_history_judge_disagreement_rate_decided_ab_mean", 0.0)), float)
        self.assertIsInstance(float(predicted.get("selected_history_judge_invalid_rate_mean", 0.0)), float)
        self.assertIsInstance(float(predicted.get("selected_history_judge_tie_rate_mean", 0.0)), float)
        self.assertIsInstance(float(predicted.get("selected_history_judge_imbalance_ab_mean", 0.0)), float)

    def test_gaps_report_from_fixture(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_gaps_mini.jsonl")
        records = lib.load_jsonl([path])
        report = gaps.summarize(records, low_count_max=1, min_family_count=3, top_k=10, missing_template_limit=10)

        fams = report.get("task_run", {}).get("families_low_template_entropy_norm_top", [])
        self.assertTrue(any(str(x.get("task_family")) == "math" and float(x.get("entropy_norm", 1.0)) == 0.0 for x in fams))

        missing = report.get("task_run", {}).get("families_missing_prompt_template_id_top", [])
        math_entry = [x for x in missing if str(x.get("task_family")) == "math"]
        self.assertEqual(len(math_entry), 1)
        self.assertEqual(math_entry[0].get("missing_prompt_template_id"), ["code.v1", "plain.v1"])

        ans_letters = report.get("task_run", {}).get("underrepresented_answer_letter_top", [])
        self.assertTrue(any(str(x.get("answer_letter")) == "B" and int(x.get("count", 0)) == 1 for x in ans_letters))
        self.assertTrue(any(str(x.get("answer_letter")) == "C" and int(x.get("count", 0)) == 1 for x in ans_letters))

        judge_low = report.get("judge_pair", {}).get("underrepresented_model_pair_top", [])
        self.assertGreaterEqual(len(judge_low), 1)

    def test_recommend_answer_letter_only_ignores_numeric_answers(self) -> None:
        history = [
            {"type": "task_run", "task_id": "math.add.001", "task_family": "math", "prompt_template_id": "cot.v1", "output": "42"},
            {"type": "task_run", "task_id": "mcq.toy.001", "task_family": "mcq", "prompt_template_id": "mcq.v1", "output": "A"},
        ]
        candidates = [
            {"task_id": "mcq.toy.002", "task_family": "mcq", "prompt_template_id": "mcq.v1", "answer": "A"},
            {"task_id": "math.add.002", "task_family": "math", "prompt_template_id": "cot.v1", "answer": "42"},
        ]
        scored = recommend._score(history, candidates, answer_weight=1.0, answer_letter_only=True)
        by_task = {c.task_id: c for c in scored}
        self.assertEqual(int(by_task["mcq.toy.002"].answer_count), 1)
        self.assertEqual(int(by_task["mcq.toy.002"].seen_answer), 1)
        self.assertEqual(int(by_task["math.add.002"].answer_count), 0)
        self.assertEqual(int(by_task["math.add.002"].seen_answer), 0)

    def test_filter_tool_annotates_and_drops_flagged_task_runs(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_filter_mini.jsonl")
        records = lib.load_jsonl([path])

        annotated = filt.annotate_records(records, drop_flagged_task_runs=False)
        self.assertEqual(len(annotated), 4)
        self.assertEqual(bool(annotated[0].get("useful_novelty_flagged", True)), False)
        self.assertEqual(list(annotated[0].get("useful_novelty_flags") or []), [])

        self.assertEqual(bool(annotated[1].get("useful_novelty_flagged", False)), True)
        self.assertGreaterEqual(len(list(annotated[1].get("useful_novelty_flags") or [])), 1)

        dropped = filt.annotate_records(records, drop_flagged_task_runs=True)
        self.assertEqual(len(dropped), 2)
        self.assertEqual(dropped[0].get("type"), "task_run")
        self.assertEqual(dropped[1].get("type"), "judge_pair")

    def test_useful_novelty_flags_respect_persisted_fields(self) -> None:
        records = [
            {
                "type": "task_run",
                "task_id": "t.clean.override",
                "task_family": "misc",
                "prompt_template_id": "plain.v1",
                "prompt": "Return JSON only.",
                "output": "As an AI language model, I cannot comply.",
                "useful_novelty_flags": [],
                "useful_novelty_flagged": False,
            },
            {
                "type": "task_run",
                "task_id": "t.flagged.persisted",
                "task_family": "misc",
                "prompt_template_id": "plain.v1",
                "prompt": "Return JSON only.",
                "output": "ok",
                "useful_novelty_flags": ["ai_disclaimer"],
                "useful_novelty_flagged": True,
            },
        ]
        report = metrics.summarize(records)
        self.assertEqual(int(report.useful_novelty.get("flagged_task_runs", 0) or 0), 1)

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

    def test_task_template_duplicate_top_exists(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_task_template_dup_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        self.assertEqual(report.diversity["task_id_template_pair"]["unique"], 2)
        top = report.duplicates.get("task_template_output_norm_dup_rate_top", [])
        self.assertGreaterEqual(len(top), 1)
        self.assertEqual(top[0].get("task_id"), "dup.task.001")
        self.assertEqual(top[0].get("prompt_template_id"), "plain.v1")
        self.assertEqual(int(top[0].get("count", 0)), 3)
        self.assertEqual(int(top[0].get("unique", 0)), 1)
        self.assertAlmostEqual(float(top[0].get("dup_rate", 0.0)), (2.0 / 3.0))

    def test_task_template_model_collapse_top_exists(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_task_template_collapse_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        top = report.duplicates.get("task_template_model_collapse_top", [])
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].get("task_id"), "collapse.task.001")
        self.assertEqual(top[0].get("task_family"), "mcq")
        self.assertEqual(top[0].get("prompt_template_id"), "plain.v1")
        self.assertEqual(int(top[0].get("count", 0)), 3)
        self.assertEqual(int(top[0].get("model_id_unique", 0)), 3)
        self.assertEqual(int(top[0].get("output_norm_unique", 0)), 1)
        self.assertAlmostEqual(float(top[0].get("collapse_rate", 0.0)), (2.0 / 3.0))

    def test_buffer_item_duplicate_top_exists(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_buffer_item_dup_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)

        top = report.duplicates.get("output_norm_dup_rate_by_buffer_item_id_top", [])
        self.assertGreaterEqual(len(top), 1)
        self.assertEqual(top[0].get("buffer_item_id"), "entropy.v1:buf.dup.001:plain.v1")
        self.assertEqual(int(top[0].get("count", 0)), 3)
        self.assertEqual(int(top[0].get("unique", 0)), 1)
        self.assertAlmostEqual(float(top[0].get("dup_rate", 0.0)), (2.0 / 3.0))

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

    def test_recommendations_penalize_unstable_judge_slices(self) -> None:
        root = _repo_root()
        hist_path = os.path.join(root, "fixtures", "entropy-buffer", "history_judge_instability_mini.jsonl")
        cand_path = os.path.join(root, "fixtures", "entropy-buffer", "candidates_judge_instability_mini.jsonl")
        history = lib.load_jsonl([hist_path])
        candidates = lib.load_jsonl([cand_path])

        scored = recommend._score(history, candidates, judge_disagree_weight=2.0, judge_invalid_weight=1.0)
        self.assertGreaterEqual(len(scored), 2)
        self.assertEqual(scored[0].prompt_template_id, "stable.v1")

    def test_judge_slice_summaries_exist(self) -> None:
        root = _repo_root()
        path = os.path.join(root, "fixtures", "entropy-buffer", "records_mini.jsonl")
        records = lib.load_jsonl([path])
        report = metrics.summarize(records)
        slices = report.judge.get("slices", {})
        by_tmpl = (slices.get("by_prompt_template_id") or {})
        top = (by_tmpl.get("count_top") or [])
        tmpl_keys = set(js.get("prompt_template_id") for js in top)
        self.assertIn("cot.v1", tmpl_keys)
        self.assertIn("mcq.letter.v1", tmpl_keys)

    def test_recommendations_avoid_seen_buffer_items(self) -> None:
        root = _repo_root()
        hist_path = os.path.join(root, "fixtures", "entropy-buffer", "history_buffer_mini.jsonl")
        cand_path = os.path.join(root, "fixtures", "entropy-buffer", "candidates_buffer_mini.jsonl")
        history = lib.load_jsonl([hist_path])
        candidates = lib.load_jsonl([cand_path])

        scored = recommend._score(history, candidates)
        self.assertGreaterEqual(len(scored), 2)
        self.assertEqual(scored[0].buffer_item_id, "entropy.v1:buf.task.003:plain.v1")

        top = recommend._select(scored, history, limit=2, max_per_family=0, max_per_template=0, avoid_seen_task_id=False, avoid_seen_buffer_item_id=True)
        self.assertGreaterEqual(len(top), 1)
        self.assertTrue(all(c.buffer_item_id != "entropy.v1:buf.task.001:plain.v1" for c in top))

    def test_recommendations_prefer_unseen_answers_when_provided(self) -> None:
        root = _repo_root()
        hist_path = os.path.join(root, "fixtures", "entropy-buffer", "history_answer_mini.jsonl")
        cand_path = os.path.join(root, "fixtures", "entropy-buffer", "candidates_answer_mini.jsonl")
        history = lib.load_jsonl([hist_path])
        candidates = lib.load_jsonl([cand_path])

        scored = recommend._score(history, candidates)
        self.assertGreaterEqual(len(scored), 3)
        self.assertEqual(scored[0].answer, "C")

        top = recommend._select(scored, history, limit=1, max_per_family=0, max_per_template=0, avoid_seen_task_id=False)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].answer, "C")

    def test_recommendations_prefer_prompt_lexical_diversity_when_enabled(self) -> None:
        root = _repo_root()
        hist_path = os.path.join(root, "fixtures", "entropy-buffer", "history_prompt_ngrams_mini.jsonl")
        cand_path = os.path.join(root, "fixtures", "entropy-buffer", "candidates_prompt_ngrams_mini.jsonl")
        history = lib.load_jsonl([hist_path])
        candidates = lib.load_jsonl([cand_path])

        scored = recommend._score(history, candidates, prompt_trigram_weight=2.0)
        top = recommend._select(scored, history, limit=1, max_per_family=0, max_per_template=0, avoid_seen_task_id=False, prompt_trigram_weight=2.0)
        self.assertEqual(len(top), 1)
        self.assertEqual(top[0].task_id, "math.prompt.aaa")

    def test_diff_key_metrics_from_before_after_fixtures(self) -> None:
        root = _repo_root()
        before_path = os.path.join(root, "fixtures", "entropy-buffer", "records_diff_before_mini.jsonl")
        after_path = os.path.join(root, "fixtures", "entropy-buffer", "records_diff_after_mini.jsonl")

        before = diff._report_dict(lib.load_jsonl([before_path]))
        after = diff._report_dict(lib.load_jsonl([after_path]))

        rows = diff._diff_paths(before, after, [
            "diversity.task_id.unique",
            "diversity.task_family.unique",
            "duplicates.output_norm_dup_rate",
            "reuse.buffer_item_reuse_event_rate",
        ])
        by_path = {r.get("path"): r for r in rows}

        self.assertEqual(by_path["diversity.task_id.unique"]["before"], 2.0)
        self.assertEqual(by_path["diversity.task_id.unique"]["after"], 3.0)
        self.assertEqual(by_path["diversity.task_id.unique"]["delta"], 1.0)

        self.assertEqual(by_path["diversity.task_family.unique"]["before"], 1.0)
        self.assertEqual(by_path["diversity.task_family.unique"]["after"], 2.0)
        self.assertEqual(by_path["diversity.task_family.unique"]["delta"], 1.0)

        self.assertAlmostEqual(by_path["duplicates.output_norm_dup_rate"]["before"], 0.0)
        self.assertAlmostEqual(by_path["duplicates.output_norm_dup_rate"]["after"], 0.25)
        self.assertAlmostEqual(by_path["duplicates.output_norm_dup_rate"]["delta"], 0.25)

        self.assertAlmostEqual(by_path["reuse.buffer_item_reuse_event_rate"]["before"], 0.0)
        self.assertAlmostEqual(by_path["reuse.buffer_item_reuse_event_rate"]["after"], 0.25)
        self.assertAlmostEqual(by_path["reuse.buffer_item_reuse_event_rate"]["delta"], 0.25)


if __name__ == "__main__":
    unittest.main()
