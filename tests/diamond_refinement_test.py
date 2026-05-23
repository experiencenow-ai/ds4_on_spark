import unittest

from scripts import diamond_refinement_domain as diamond


class DiamondRefinementTest(unittest.TestCase):
    def test_synthetic_inline_path_produces_verified_diamond_delta(self) -> None:
        record = diamond.run_synthetic()
        self.assertEqual(
            (
                record["format"],
                record["status"],
                record["frontier_call_count"],
                record["local_model_call_count"],
                record["sandbox_isolation"],
                record["behavior"]["byte_identical_output"],
            ),
            (diamond.FORMAT, "passed", 0, 0, True, True),
        )
        self.assertGreater(record["diamond_delta"], 0)
        self.assertEqual(record["source"]["audit"]["loc"], 4)
        self.assertEqual(record["candidate"]["audit"]["loc"], 2)
        self.assertEqual(record["candidate"]["audit"]["single_caller_helper_count"], 0)
        self.assertIn("score_candidate", [node["node"] for node in record["nodes"]])

if __name__ == "__main__":
    unittest.main()
