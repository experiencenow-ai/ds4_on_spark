import copy
import unittest
from pathlib import Path

from scripts import run_ds4_sglang_provider_probe as runner
from scripts import validate_ds4_sglang_provider_probe as validator


FIXTURE = Path("fixtures/sglang_provider_probe/sglang_provider_probe_local_blocked.example.json")


class SglangProviderProbeTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validator.validate_paths([FIXTURE])
        self.assertTrue(result["ok"], result["errors"])

    def test_required_benchmark_cases_are_present(self) -> None:
        probe = validator.load_json(FIXTURE)
        cases = {case["case_id"]: case for case in probe["benchmark_results"]}
        self.assertEqual(set(cases), validator.REQUIRED_CASES)
        self.assertEqual(cases["b1_full_vocab_chat"]["batch_size"], 1)
        self.assertEqual(cases["b4_q_numbered_full_vocab_rows"]["batch_size"], 4)
        self.assertEqual(cases["b16_full_vocab_rows"]["batch_size"], 16)
        self.assertEqual(cases["b512_full_vocab_one_token"]["batch_size"], 512)

    def test_blocked_probe_does_not_report_speed_or_successful_load(self) -> None:
        probe = validator.load_json(FIXTURE)
        self.assertFalse(probe["load_success"])
        self.assertEqual(probe["blocker_kind"], "sglang_not_installed")
        for case in probe["benchmark_results"]:
            self.assertEqual(case["status"], "blocked")
            self.assertIsNone(case["tokens_per_second"])

    def test_constrained_unknown_cannot_infer_speedup(self) -> None:
        probe = validator.load_json(FIXTURE)
        constrained = [case for case in probe["benchmark_results"] if case["case_id"] == "b512_constrained_structured_output"][0]
        self.assertEqual(constrained["constrained_scoring"], "unknown")
        self.assertFalse(constrained["custom_ds4_speedup_inferred"])
        bad = copy.deepcopy(probe)
        bad["benchmark_results"] = copy.deepcopy(probe["benchmark_results"])
        for case in bad["benchmark_results"]:
            if case["case_id"] == "b512_constrained_structured_output":
                case["custom_ds4_speedup_inferred"] = True
        bad["artifact_sha256"] = validator.artifact_sha256(bad)
        bad["artifact_hash"] = bad["artifact_sha256"]
        errors = validator.validate_probe(bad)
        self.assertTrue(any("constrained output speedup" in item for item in errors))

    def test_artifact_hash_detects_tampering(self) -> None:
        probe = validator.load_json(FIXTURE)
        tampered = copy.deepcopy(probe)
        tampered["provider_id"] = "changed"
        errors = validator.validate_probe(tampered)
        self.assertTrue(any("artifact_sha256" in item for item in errors))

    def test_rejects_fixed_spark_count_fields(self) -> None:
        probe = validator.load_json(FIXTURE)
        probe["spark_count"] = 3
        errors = validator.validate_probe(probe)
        self.assertTrue(any("fixed Spark count" in item for item in errors))

    def test_runner_builds_not_installed_blocker_without_live_launch(self) -> None:
        class Args:
            run_id = "unit"
            provider_id = "sglang-ds4-local"
            model_id = "deepseek-ai/DeepSeek-V4-Flash"
            checkpoint_format = "huggingface"
            runtime_id = "sglang-local-probe"
            model_path = "/path/that/does/not/exist"
            recipe = "custom"
            mtp_enabled = False
            mtp_draft_tokens = 2
            max_running_requests = 512
            tp_size = 1
            pp_size = 1
            dp_size = 1
            allow_launch = False

        probe = runner.build_probe(Args())
        self.assertIn(probe["blocker_kind"], {"sglang_not_installed", "model_checkpoint_missing"})
        self.assertEqual(validator.validate_probe(probe), [])


if __name__ == "__main__":
    unittest.main()
