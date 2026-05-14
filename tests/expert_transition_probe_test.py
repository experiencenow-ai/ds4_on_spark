import unittest

from sim.scheduler import expert_transition_probe


class ExpertTransitionProbeTest(unittest.TestCase):
    def test_conditional_next_expert_stats_and_affinity_map(self) -> None:
        layers = [
            [[0, 1], [0, 1], [2, 3], [2, 3]],
            [[4, 5], [4, 5], [6, 7], [6, 7]],
        ]
        cfg = expert_transition_probe.ExpertTransitionProbeConfig(
            experts=8,
            topk=2,
            logical_lanes=8,
            sparks=2,
            top_masses=(1, 2, 4),
            top_next=4,
        )
        out = expert_transition_probe.analyze_expert_transitions(layers, cfg)
        cond = out["conditional"]["summary"]
        same = out["same_spark"]
        self.assertEqual(out["pair_transitions"], 16)
        self.assertAlmostEqual(cond["weighted_top1_mass"], 0.5, places=6)
        self.assertAlmostEqual(cond["weighted_top2_mass"], 1.0, places=6)
        self.assertAlmostEqual(same["mod_lane_same_spark_rate"], 0.0, places=6)
        self.assertAlmostEqual(same["affinity_same_spark_rate"], 1.0, places=6)
        self.assertEqual(out["affinity_spark_tables"][1][4:8], [0, 0, 0, 0])

    def test_mod_lane_table_keeps_expert_id_mod_logical_lanes(self) -> None:
        cfg = expert_transition_probe.ExpertTransitionProbeConfig(experts=16, logical_lanes=8, sparks=4)
        table = expert_transition_probe.build_mod_lane_spark_table(cfg)
        self.assertEqual(table[0], table[8])
        self.assertEqual(table[1], table[9])
        self.assertEqual(table[7], table[15])

    def test_rejects_out_of_range_when_strict(self) -> None:
        layers = [
            [[0, 99]],
            [[1, 2]],
        ]
        cfg = expert_transition_probe.ExpertTransitionProbeConfig(experts=8, topk=2, strict_expert_ids=True)
        with self.assertRaises(ValueError):
            expert_transition_probe.analyze_expert_transitions(layers, cfg)

    def test_compact_report_strips_large_tables(self) -> None:
        layers = [
            [[0, 1], [0, 1]],
            [[2, 3], [2, 3]],
        ]
        cfg = expert_transition_probe.ExpertTransitionProbeConfig(experts=4, topk=2, logical_lanes=4, sparks=2)
        out = expert_transition_probe.analyze_expert_transitions(layers, cfg)
        compact = expert_transition_probe.as_compact_report(out)
        self.assertIn("same_spark", compact)
        self.assertNotIn("affinity_spark_tables", compact)

    def test_owner_table_artifact_is_balanced_and_keeps_tables(self) -> None:
        layers = [
            [[0, 1], [0, 1], [2, 3], [2, 3]],
            [[4, 5], [4, 5], [6, 7], [6, 7]],
        ]
        cfg = expert_transition_probe.ExpertTransitionProbeConfig(
            experts=8,
            topk=2,
            logical_lanes=8,
            sparks=2,
            top_masses=(1, 2, 4),
            top_next=4,
        )
        result = expert_transition_probe.analyze_expert_transitions(layers, cfg)
        artifact = expert_transition_probe.build_owner_table_artifact(result)
        self.assertEqual(artifact["schema"], "ds4_expert_owner_table_v1")
        self.assertEqual(artifact["strategy"], "affinity")
        self.assertEqual(len(artifact["owner_table"]), 2)
        self.assertEqual(artifact["owner_table"][1][4:8], [0, 0, 0, 0])
        counts = artifact["table_balance"]["per_layer_counts"]
        self.assertEqual(counts, [[4, 4], [4, 4]])


if __name__ == "__main__":
    unittest.main()
