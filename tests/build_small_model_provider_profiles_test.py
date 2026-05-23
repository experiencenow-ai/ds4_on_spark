import tempfile
import unittest
from pathlib import Path

from scripts import build_small_model_provider_profiles as builder
from scripts import validate_model_provider_profiles as validator


class BuildSmallModelProviderProfilesTest(unittest.TestCase):
    def test_selects_fastest_perfect_pass_rate_records(self) -> None:
        addendum = builder.load_json(builder.ADDENDUM)
        selected = builder.select_records(addendum)
        self.assertEqual(selected["local_small"]["model_id"], "hf-Qwen-Qwen3.5-2B")
        self.assertEqual(selected["local_coder"]["model_id"], "hf-Qwen-Qwen3.5-2B")
        self.assertEqual(selected["local_small"]["pass_rate"], 1.0)
        self.assertGreater(selected["local_small"]["mean_tok_s"], 20.0)

    def test_generated_profiles_validate_as_production_eligible(self) -> None:
        addendum = builder.load_json(builder.ADDENDUM)
        selected = builder.select_records(addendum)
        for tier, row in selected.items():
            profile = builder.profile_from_row(tier, row)
            self.assertTrue(profile["production_eligible"])
            self.assertEqual(profile["runtime"], "transformers_cli")
            self.assertGreater(profile["measured_output_tps"], 0.0)
            errors = validator.validate_profile(profile, Path(f"{tier}.json"))
            self.assertEqual(errors, [])

    def test_writer_uses_stable_profile_paths(self) -> None:
        addendum = builder.load_json(builder.ADDENDUM)
        selected = builder.select_records(addendum)
        profiles = {tier: builder.profile_from_row(tier, row) for tier, row in selected.items()}
        with tempfile.TemporaryDirectory() as tmp:
            paths = builder.write_profiles(Path(tmp), profiles)
            names = sorted(path.name for path in paths)
        self.assertEqual(
            names,
            [
                "spark2-hf-qwen-qwen3-5-2b-local_coder-measured.example.json",
                "spark2-hf-qwen-qwen3-5-2b-local_small-measured.example.json",
            ],
        )


if __name__ == "__main__":
    unittest.main()
