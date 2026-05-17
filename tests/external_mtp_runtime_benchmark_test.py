import copy
import unittest
from pathlib import Path

from scripts import validate_ds4_external_mtp_runtime_benchmark as validator


FIXTURE = Path("fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark0_20260517.example.json")


class ExternalMtpRuntimeBenchmarkTest(unittest.TestCase):
    def test_fixture_validates(self) -> None:
        result = validator.validate_paths([FIXTURE])
        self.assertTrue(result["ok"], result["errors"])

    def test_blocked_attempt_cannot_claim_speed(self) -> None:
        obj = validator.load_json(FIXTURE)
        bad = copy.deepcopy(obj)
        bad["runtime_attempts"][0]["baseline_generation_tps"] = 10.0
        bad["runtime_attempts"][0]["mtp_generation_tps"] = 18.0
        bad["runtime_attempts"][0]["speedup_vs_baseline"] = 1.8
        bad["artifact_sha256"] = validator.canonical_hash(bad)
        bad["artifact_hash"] = bad["artifact_sha256"]
        errors = validator.validate_artifact(bad, Path("bad.json"))
        self.assertTrue(any("must not claim speed metrics" in item for item in errors))

    def test_passed_attempt_requires_consistent_speedup(self) -> None:
        obj = validator.load_json(FIXTURE)
        good = copy.deepcopy(obj)
        attempt = good["runtime_attempts"][0]
        attempt["benchmark_status"] = "passed"
        attempt["blocker_kind"] = "none"
        attempt["blocker_detail"] = ""
        attempt["ds4_model_supported"] = True
        attempt["baseline_generation_tps"] = 10.0
        attempt["mtp_generation_tps"] = 18.0
        attempt["speedup_vs_baseline"] = 1.2
        good["artifact_sha256"] = validator.canonical_hash(good)
        good["artifact_hash"] = good["artifact_sha256"]
        errors = validator.validate_artifact(good, Path("bad.json"))
        self.assertTrue(any("speedup_vs_baseline must match" in item for item in errors))

    def test_missing_runtime_attempt_is_rejected(self) -> None:
        obj = validator.load_json(FIXTURE)
        bad = copy.deepcopy(obj)
        bad["runtime_attempts"] = [item for item in bad["runtime_attempts"] if item["runtime"] != "vllm"]
        bad["artifact_sha256"] = validator.canonical_hash(bad)
        bad["artifact_hash"] = bad["artifact_sha256"]
        errors = validator.validate_artifact(bad, Path("bad.json"))
        self.assertTrue(any("missing runtime attempt" in item for item in errors))

    def test_hash_mismatch_is_rejected(self) -> None:
        obj = validator.load_json(FIXTURE)
        obj["target_model_id"] = "changed"
        errors = validator.validate_artifact(obj, Path("bad.json"))
        self.assertTrue(any("artifact_sha256" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
