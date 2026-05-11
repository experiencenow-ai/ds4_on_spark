import os
import tempfile
import unittest

from scripts import judge_elo_schema as schema
from scripts import judge_elo_update as updater


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


if __name__ == "__main__":
    unittest.main()
