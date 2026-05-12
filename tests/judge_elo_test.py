import json
import os
import subprocess
import tempfile
import unittest

from scripts import judge_elo_schema as schema
from scripts import judge_elo_join_quality as joiner
from scripts import judge_elo_update as updater
from scripts import pairwise_judge_record as record_wrap


class JudgeEloTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        bad = 0
        for _, obj in schema.iter_jsonl(path):
            errs = schema.validate_record(obj)
            if len(errs) != 0:
                bad += 1
        # One intentionally parse-invalid record is still schema-valid.
        self.assertEqual(bad, 0)

    def test_elo_deterministic(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        ratings1, stats1 = updater.compute_elo([path], k=32.0, scale=400.0, sort_by_pair_id=False)
        ratings2, stats2 = updater.compute_elo([path], k=32.0, scale=400.0, sort_by_pair_id=False)
        self.assertEqual(stats1, stats2)
        self.assertEqual(set(ratings1.keys()), set(ratings2.keys()))
        for k in ratings1:
            self.assertAlmostEqual(ratings1[k], ratings2[k], places=9)

    def test_sort_by_pair_id_is_stable(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        m1 = list(updater.iter_valid_matches([path], sort_by_pair_id=False))
        m2 = list(updater.iter_valid_matches([path], sort_by_pair_id=True))
        self.assertEqual(m1, m2)

    def test_output_files_written(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        with tempfile.TemporaryDirectory() as td:
            ratings, stats = updater.compute_elo([path], k=32.0, scale=400.0, sort_by_pair_id=False)
            q = updater._quality_minmax(ratings)
            rows = []
            for model, elo in ratings.items():
                st = stats[model]
                rows.append(updater.EloRow(
                    model=model,
                    elo=float(elo),
                    games=int(st["games"]),
                    wins=int(st["wins"]),
                    losses=int(st["losses"]),
                    ties=int(st["ties"]),
                    quality_score=float(q[model]),
                    quality_source="judge_elo_minmax_v1",
                ))
            rows.sort(key=lambda r: r.elo, reverse=True)
            updater.write_outputs(td, rows)
            self.assertTrue(os.path.exists(os.path.join(td, "leaderboard.json")))
            self.assertTrue(os.path.exists(os.path.join(td, "leaderboard.csv")))
            self.assertTrue(os.path.exists(os.path.join(td, "leaderboard.md")))
            self.assertTrue(os.path.exists(os.path.join(td, "quality_map.json")))

    def test_budget_computed(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        budget = updater.compute_budget([path])
        self.assertEqual(budget.get("schema"), "ds4_judge_elo_budget_v1")
        self.assertEqual(int(budget.get("records", 0)), 4)
        self.assertIn("tokens", budget)
        self.assertIn("latency_ms", budget)
        self.assertIn("judge_out_budget", budget)

    def test_budget_target_is_configurable(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        budget = updater.compute_budget([path], judge_out_target=42)
        j = budget.get("judge_out_budget", {})
        self.assertEqual(int(j.get("target_tokens", 0)), 42)

    def test_meta_computed(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        meta = updater.compute_meta([path], k=32.0, scale=400.0, sort_by_pair_id=False)
        self.assertEqual(meta.get("schema"), "ds4_judge_elo_meta_v1")
        self.assertEqual(int(meta.get("records", 0)), 4)
        self.assertGreaterEqual(int(meta.get("matches_used", 0)), 3)

    def test_elo_expected_values(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(root, "fixtures", "judge-elo", "sample_judge_records.jsonl")
        ratings, _stats = updater.compute_elo([path], k=32.0, scale=400.0, sort_by_pair_id=False)
        self.assertAlmostEqual(float(ratings.get("model_slow", 0.0)), 1008.736, places=3)
        self.assertAlmostEqual(float(ratings.get("model_mid", 0.0)), 999.899, places=3)
        self.assertAlmostEqual(float(ratings.get("model_fast", 0.0)), 991.364, places=3)

    def test_join_quality_rows(self) -> None:
        rows = [
            {"model": "model_fast", "decode_tps": "100.0"},
            {"model": "model_mid", "decode_tps": "80.0", "quality_score": ""},
            {"model": "missing_model", "decode_tps": "50.0"},
        ]
        qmap = {"model_fast": 70.0, "model_mid": 55.5}
        joined, missing = joiner.join_quality_rows(
            rows=rows,
            quality_map=qmap,
            quality_source="testsrc",
            model_field="model",
            overwrite=True,
            require_all=False,
        )
        self.assertEqual(missing, 1)
        self.assertEqual(joined[0].get("quality_score"), "70.000")
        self.assertEqual(joined[0].get("quality_source"), "testsrc")
        self.assertEqual(joined[1].get("quality_score"), "55.500")
        self.assertEqual(joined[2].get("quality_score", ""), "")

    def test_wrap_record_parse_valid(self) -> None:
        decision = {"winner": "A", "margin": 2, "score_a": 8, "score_b": 6, "reason": "A is more correct.", "train_hint": "Fix the key mistake.", "tags": ["factuality"]}
        rec = record_wrap.build_record(
            pair_id="p0",
            model_a="mA",
            model_b="mB",
            judge_model="ds4",
            decision_text="  \n" + json.dumps(decision, separators=(",", ":")) + "\n",
            tokens={"a_out": 1, "b_out": 2, "judge_in": 3, "judge_out": 4},
            latency_ms={"a": 5, "b": 6, "judge": 7},
        )
        self.assertTrue(rec.get("parse_valid", False))
        self.assertEqual(rec.get("winner"), "A")

    def test_wrap_record_parse_invalid(self) -> None:
        rec = record_wrap.build_record(
            pair_id="p1",
            model_a="mA",
            model_b="mB",
            judge_model="ds4",
            decision_text="WINNER=A margin=2",
            tokens=None,
            latency_ms=None,
        )
        self.assertFalse(rec.get("parse_valid", True))

    def test_parse_json_object_loose_extracts_first_object(self) -> None:
        decision = {"winner": "tie", "margin": 0, "score_a": 6, "score_b": 6, "reason": "Both are acceptable.", "train_hint": "", "tags": []}
        text = "NOTE {not json}\n" + json.dumps(decision, separators=(",", ":"), ensure_ascii=False) + "\nTRAILING"
        obj, perr = schema.parse_json_object_loose(text)
        self.assertEqual(perr, "")
        self.assertIsInstance(obj, dict)
        self.assertEqual(obj.get("winner"), "tie")

    def test_decision_reason_char_limit(self) -> None:
        decision = {
            "winner": "A",
            "margin": 1,
            "score_a": 7,
            "score_b": 6,
            "reason": ("x" * 201),
            "train_hint": "",
            "tags": [],
        }
        errs = schema.validate_decision(decision)
        self.assertTrue(any("<= 200 chars" in e for e in errs))

    def test_decision_strings_single_line(self) -> None:
        decision = {
            "winner": "A",
            "margin": 1,
            "score_a": 7,
            "score_b": 6,
            "reason": "line1\nline2",
            "train_hint": "ok",
            "tags": ["clean"],
        }
        errs = schema.validate_decision(decision)
        self.assertTrue(any("reason must be a single line" in e for e in errs))

        decision2 = dict(decision)
        decision2["reason"] = "ok"
        decision2["train_hint"] = "hint\rmore"
        errs2 = schema.validate_decision(decision2)
        self.assertTrue(any("train_hint must be a single line" in e for e in errs2))

        decision3 = dict(decision)
        decision3["reason"] = "ok"
        decision3["train_hint"] = "ok"
        decision3["tags"] = ["ok", "bad\ntag"]
        errs3 = schema.validate_decision(decision3)
        self.assertTrue(any("tags[1] must be a single line" in e for e in errs3))

    def test_record_raw_char_limit(self) -> None:
        rec = {
            "schema": schema.SCHEMA_RECORD_V1,
            "pair_id": "p0",
            "model_a": "mA",
            "model_b": "mB",
            "judge_model": "ds4",
            "parse_valid": False,
            "raw": ("y" * 513),
            "parse_error": "oops",
        }
        errs = schema.validate_record(rec)
        self.assertTrue(any("raw must be <= 512 chars" in e for e in errs))

    def test_wrap_record_sanitizes_raw_newlines(self) -> None:
        rec = record_wrap.build_record(
            pair_id="p_nl",
            model_a="mA",
            model_b="mB",
            judge_model="ds4",
            decision_text="not json\nline2\rline3",
            tokens=None,
            latency_ms=None,
        )
        self.assertFalse(rec.get("parse_valid", True))
        raw = str(rec.get("raw", ""))
        perr = str(rec.get("parse_error", ""))
        self.assertNotIn("\n", raw)
        self.assertNotIn("\r", raw)
        self.assertNotIn("\n", perr)
        self.assertNotIn("\r", perr)

    def test_pairwise_judge_record_cli_accepts_partial_tokens_latency(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        script = os.path.join(root, "scripts", "pairwise_judge_record.py")
        with tempfile.TemporaryDirectory() as td:
            dec_path = os.path.join(td, "decision.txt")
            with open(dec_path, "w", encoding="utf-8") as f:
                f.write("{\"winner\":\"A\",\"margin\":1,\"score_a\":7,\"score_b\":6,\"reason\":\"ok\",\"train_hint\":\"\",\"tags\":[\"clarity\"]}\n")
            out = subprocess.check_output([
                "python3",
                script,
                "--pair-id",
                "p0",
                "--model-a",
                "mA",
                "--model-b",
                "mB",
                "--judge-model",
                "ds4",
                "--decision",
                dec_path,
                "--tokens-judge-out",
                "40",
                "--latency-judge-ms",
                "123",
            ], text=True)
            obj = json.loads(out)
            self.assertTrue(bool(obj.get("parse_valid", False)))
            self.assertEqual(obj.get("tokens"), {"judge_out": 40})
            self.assertEqual(obj.get("latency_ms"), {"judge": 123})
            self.assertEqual(schema.validate_record(obj), [])

    def test_pairwise_judge_prompt_cli_json_format(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        script = os.path.join(root, "scripts", "pairwise_judge_prompt.py")
        with tempfile.TemporaryDirectory() as td:
            p_path = os.path.join(td, "prompt.txt")
            a_path = os.path.join(td, "a.txt")
            b_path = os.path.join(td, "b.txt")
            with open(p_path, "w", encoding="utf-8") as f:
                f.write("Explain what ELO rating means.\n")
            with open(a_path, "w", encoding="utf-8") as f:
                f.write("Elo is a rating system used for head-to-head games.\n")
            with open(b_path, "w", encoding="utf-8") as f:
                f.write("ELO is a ranking thing.\n")
            out = subprocess.check_output([
                "python3",
                script,
                "--prompt",
                p_path,
                "--a",
                a_path,
                "--b",
                b_path,
                "--judge-out-target",
                "64",
                "--format",
                "json",
            ], text=True)
            obj = json.loads(out)
            self.assertEqual(obj.get("schema"), "ds4_pairwise_judge_prompt_v1")
            self.assertIn("system", obj)
            self.assertIn("user", obj)
            self.assertIn("schema_hint", obj)
            self.assertIn("Return minified JSON only", str(obj.get("system", "")))
            self.assertIn("PROMPT:", str(obj.get("user", "")))

    def test_json_schema_files_present(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        dec_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "ds4_pairwise_judge_decision_v1.schema.json")
        rec_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "ds4_pairwise_judge_record_v1.schema.json")
        meta_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "ds4_judge_elo_meta_v1.schema.json")
        budget_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "ds4_judge_elo_budget_v1.schema.json")
        qmap_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "judge_elo_quality_map_v1.schema.json")
        leaderboard_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "judge_elo_leaderboard_v1.schema.json")
        for path in (dec_path, rec_path, meta_path, budget_path, qmap_path, leaderboard_path):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if path.endswith("leaderboard_v1.schema.json"):
                self.assertIsInstance(obj, dict)
                self.assertEqual(obj.get("type"), "array")
                self.assertIn("items", obj)
            else:
                self.assertIsInstance(obj, dict)
                self.assertEqual(obj.get("type"), "object")
                # Decision/record/meta/budget schemas expose properties; the quality_map schema uses additionalProperties.
                self.assertTrue(("properties" in obj) or ("additionalProperties" in obj))


if __name__ == "__main__":
    unittest.main()
