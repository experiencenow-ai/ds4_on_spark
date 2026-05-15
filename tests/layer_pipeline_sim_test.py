import unittest

from sim.pipeline.layer_pipeline_sim import balanced_stage_ms
from sim.pipeline.layer_pipeline_sim import normalize_transfers
from sim.pipeline.layer_pipeline_sim import simulate


class LayerPipelineSimTest(unittest.TestCase):
    def test_balanced_three_stage_pipeline_approaches_three_x(self) -> None:
        row = simulate([10.0, 10.0, 10.0], [], 32)
        self.assertEqual(row.bottleneck_stage, 0)
        self.assertAlmostEqual(row.pipeline_wall_ms, 340.0)
        self.assertAlmostEqual(row.speedup_vs_serial, 960.0 / 340.0)
        self.assertAlmostEqual(row.bubble_overhead_ratio, 20.0 / 340.0)

    def test_single_microbatch_has_no_throughput_gain(self) -> None:
        row = simulate([10.0, 10.0, 10.0], [], 1)
        self.assertAlmostEqual(row.pipeline_wall_ms, 30.0)
        self.assertAlmostEqual(row.speedup_vs_serial, 1.0)

    def test_imbalanced_stage_is_bottleneck(self) -> None:
        row = simulate([5.0, 20.0, 5.0], [1.0, 1.0], 16)
        self.assertEqual(row.bottleneck_stage, 1)
        self.assertAlmostEqual(row.bottleneck_interval_ms, 21.0)
        self.assertGreater(row.stage_balance_ratio, 1.5)

    def test_transfer_list_can_omit_final_stage(self) -> None:
        self.assertEqual(normalize_transfers(3, [1.0, 2.0]), [1.0, 2.0, 0.0])

    def test_balanced_stage_builder(self) -> None:
        self.assertEqual(balanced_stage_ms(45.0, 3), [15.0, 15.0, 15.0])


if __name__ == "__main__":
    unittest.main()
