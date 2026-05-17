import copy
import unittest
from pathlib import Path

from scripts import validate_centaur_standard_runtime_benchmark as benchmark_validator
from scripts import validate_model_provider_profiles as profile_validator


class StandardRuntimeModelBenchmarkTest(unittest.TestCase):
    def test_fixture_benchmarks_validate(self) -> None:
        paths = benchmark_validator.default_benchmark_paths()
        self.assertGreaterEqual(len(paths), 5)
        result = benchmark_validator.validate_paths(paths)
        self.assertTrue(result["ok"], result["errors"])

    def test_blocked_benchmark_cannot_claim_speed(self) -> None:
        path = Path("fixture.json")
        obj = benchmark_validator.load_benchmark(benchmark_validator.default_benchmark_paths()[0])
        obj = copy.deepcopy(obj)
        obj["tokens_per_second"] = 42.0
        obj["artifact_sha256"] = benchmark_validator.canonical_hash(obj)
        errors = benchmark_validator.validate_benchmark(obj, path)
        self.assertTrue(any("blocked benchmark must not claim" in item for item in errors))

    def test_mtp_enabled_requires_mtp_supported(self) -> None:
        path = Path("fixture.json")
        obj = benchmark_validator.load_benchmark(benchmark_validator.default_benchmark_paths()[0])
        obj = copy.deepcopy(obj)
        obj["blocker_kind"] = "none"
        obj["blocker_detail"] = ""
        obj["tokens_per_second"] = 10.0
        obj["time_to_first_token_ms"] = 10.0
        obj["prompt_processing_tokens_per_second"] = 100.0
        obj["memory_used_gib"] = 1.0
        obj["parse_valid"] = True
        obj["mtp_supported"] = False
        obj["mtp_enabled"] = True
        obj["artifact_sha256"] = benchmark_validator.canonical_hash(obj)
        errors = benchmark_validator.validate_benchmark(obj, path)
        self.assertTrue(any("mtp_enabled requires" in item for item in errors))

    def test_constrained_success_requires_candidate_only_semantics(self) -> None:
        path = Path("fixture.json")
        fixture = [item for item in benchmark_validator.default_benchmark_paths() if item.name == "sglang_structured_output_semantics_blocked.example.json"][0]
        obj = benchmark_validator.load_benchmark(fixture)
        obj = copy.deepcopy(obj)
        obj["output_mode"] = "constrained_candidate"
        obj["blocker_kind"] = "none"
        obj["blocker_detail"] = ""
        obj["tokens_per_second"] = 100.0
        obj["time_to_first_token_ms"] = 20.0
        obj["prompt_processing_tokens_per_second"] = 300.0
        obj["memory_used_gib"] = 20.0
        obj["parse_valid"] = True
        obj["structured_output_semantics"] = "full_vocab_plus_mask_or_unknown"
        obj["artifact_sha256"] = benchmark_validator.canonical_hash(obj)
        errors = benchmark_validator.validate_benchmark(obj, path)
        self.assertTrue(any("candidate_only_scoring" in item for item in errors))

    def test_hash_mismatch_rejected(self) -> None:
        path = Path("fixture.json")
        obj = benchmark_validator.load_benchmark(benchmark_validator.default_benchmark_paths()[0])
        obj = copy.deepcopy(obj)
        obj["model_id"] = "tampered"
        errors = benchmark_validator.validate_benchmark(obj, path)
        self.assertTrue(any("artifact_sha256 does not match" in item for item in errors))

    def test_rejects_fixed_spark_count_fields(self) -> None:
        path = Path("fixture.json")
        obj = benchmark_validator.load_benchmark(benchmark_validator.default_benchmark_paths()[0])
        obj = copy.deepcopy(obj)
        obj["world_size"] = 3
        obj["artifact_sha256"] = benchmark_validator.canonical_hash(obj)
        errors = benchmark_validator.validate_benchmark(obj, path)
        self.assertTrue(any("fixed Spark count" in item for item in errors))

    def test_centaur_provider_profile_fixtures_validate(self) -> None:
        paths = [item for item in profile_validator.default_profile_paths() if item.name.startswith("standard_")]
        self.assertGreaterEqual(len(paths), 3)
        result = profile_validator.validate_paths(paths)
        self.assertTrue(result["ok"], result["errors"])


if __name__ == "__main__":
    unittest.main()
