import json
import os
import tempfile
import unittest

from scripts import judge_elo_schema as schema
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

    def test_json_schema_files_present(self) -> None:
        root = os.path.dirname(os.path.dirname(__file__))
        dec_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "ds4_pairwise_judge_decision_v1.schema.json")
        rec_path = os.path.join(root, "fixtures", "judge-elo", "schemas", "ds4_pairwise_judge_record_v1.schema.json")
        for path in (dec_path, rec_path):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            self.assertIsInstance(obj, dict)
            self.assertEqual(obj.get("type"), "object")
            self.assertIn("properties", obj)


if __name__ == "__main__":
    unittest.main()
