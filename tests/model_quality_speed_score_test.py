import csv
import io
import unittest

from scripts import model_quality_speed_score as scorer


class ModelQualitySpeedScoreTest(unittest.TestCase):
    def _rows(self, text: str):
        return(list(csv.DictReader(io.StringIO(text))))

    def test_quality_score_from_local_and_public(self) -> None:
        rows = scorer.score_rows(self._rows(
            "model,public_quality_prior,passed_tasks,total_tasks,decode_tps\n"
            "ling,61.2,8,10,40\n"
        ))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].quality_source, "local70_public30")
        self.assertAlmostEqual(rows[0].local_quality_score or 0.0, 80.0)
        self.assertAlmostEqual(rows[0].quality_score or 0.0, 74.36)
        self.assertAlmostEqual(rows[0].quality_adjusted_decode_tps or 0.0, 29.744)

    def test_pareto_marks_dominated_row(self) -> None:
        rows = scorer.score_rows(self._rows(
            "model,quality_score,decode_tps\n"
            "slow_low,70,10\n"
            "fast_high,80,12\n"
        ))
        by_model = {r.model: r for r in rows}
        self.assertEqual(by_model["slow_low"].dominated_by, "fast_high")
        self.assertEqual(by_model["fast_high"].dominated_by, "")

    def test_correct_task_rate_and_tokens_per_success(self) -> None:
        rows = scorer.score_rows(self._rows(
            "model,passed_tasks,total_tasks,total_wall_s,output_tokens,public_quality_prior\n"
            "qwen,4,5,20,400,72\n"
        ), speed_field="correct_tasks_per_s")
        self.assertAlmostEqual(rows[0].correct_task_rate or 0.0, 0.8)
        self.assertAlmostEqual(rows[0].correct_tasks_per_s or 0.0, 0.2)
        self.assertAlmostEqual(rows[0].tokens_per_success or 0.0, 100.0)
        self.assertAlmostEqual(rows[0].wall_s_per_success or 0.0, 5.0)


if __name__ == "__main__":
    unittest.main()
