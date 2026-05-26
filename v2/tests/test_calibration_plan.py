from __future__ import annotations

import unittest

from ds4_calibrate.plan import build_calibration_plan


class CalibrationPlanTests(unittest.TestCase):
    def test_ladder_contains_requested_batches(self) -> None:
        points = build_calibration_plan(profile_id="p", modes=["completion"], batch_sizes=[1, 2, 4], input_buckets=["0_1k"], output_buckets=["0_256"], thinking_buckets=["none"])
        self.assertEqual([point.batch_size for point in points], [1, 2, 4])
        self.assertEqual(points[0].to_json()["format"], "ds4-calibration-point-v1")


if __name__ == "__main__":
    unittest.main()
