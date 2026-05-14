import unittest

from scripts import ds4_expert_mod32_ceiling as ceiling


class Ds4ExpertMod32CeilingTest(unittest.TestCase):
    def test_expert_id_maps_to_mod32_lane(self) -> None:
        self.assertEqual(ceiling.expert_lane(0, 32), 0)
        self.assertEqual(ceiling.expert_lane(31, 32), 31)
        self.assertEqual(ceiling.expert_lane(32, 32), 0)
        self.assertEqual(ceiling.expert_lane(255, 32), 31)

    def test_eight_sparks_own_four_lanes_each(self) -> None:
        cfg = ceiling.CeilingConfig()
        report = ceiling.build_report(cfg)
        self.assertEqual(report["lane_map"][0]["expert_ids"], [0, 32, 64, 96, 128, 160, 192, 224])
        self.assertEqual(report["lane_map"][31]["expert_ids"], [31, 63, 95, 127, 159, 191, 223, 255])
        self.assertEqual(report["spark_summary"][0]["lane_ids"], [0, 1, 2, 3])
        self.assertEqual(report["spark_summary"][7]["lane_ids"], [28, 29, 30, 31])
        self.assertTrue(all(row["expert_count"] == 32 for row in report["spark_summary"]))

    def test_ceiling_math_uses_topk_times_layers(self) -> None:
        cfg = ceiling.CeilingConfig(pairs_per_s_per_spark=159700.0, sparks=8, topk=6, layers=43)
        out = ceiling.compute_ceilings(cfg)
        self.assertEqual(out["layer_pairs_per_output_token"], 258.0)
        self.assertAlmostEqual(out["moe_only_tok_s_per_spark"], 618.9922480620155, places=6)
        self.assertAlmostEqual(out["moe_only_tok_s_cluster"], 4951.937984496124, places=6)
        self.assertAlmostEqual(out["ffn_envelope_tok_s_cluster"], (24007.073 / 43.0) * 8.0, places=6)

    def test_non_divisible_spark_count_still_maps_all_lanes(self) -> None:
        cfg = ceiling.CeilingConfig(sparks=7)
        report = ceiling.build_report(cfg)
        lanes = []
        for row in report["spark_summary"]:
            lanes.extend(row["lane_ids"])
        self.assertEqual(sorted(lanes), list(range(32)))
        self.assertEqual(sum(int(row["expert_count"]) for row in report["spark_summary"]), 256)


if __name__ == "__main__":
    unittest.main()
