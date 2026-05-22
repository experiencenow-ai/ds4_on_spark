import copy
import unittest
from pathlib import Path

from scripts import validate_model_provider_profiles as validator


class ModelProviderProfilesTest(unittest.TestCase):
    def test_fixture_profiles_validate(self) -> None:
        paths = validator.default_profile_paths()
        self.assertGreaterEqual(len(paths), 4)
        result = validator.validate_paths(paths)
        self.assertTrue(result["ok"], result["errors"])

    def test_measured_throughput_requires_probe_artifact(self) -> None:
        path = Path("fixture.json")
        obj = validator.load_profile(validator.default_profile_paths()[0])
        obj = copy.deepcopy(obj)
        obj["measured_output_tps"] = 42.0
        obj["last_probe_artifact"] = ""
        errors = validator.validate_profile(obj, path)
        self.assertTrue(any("last_probe_artifact" in item for item in errors))

    def test_rejects_fixed_spark_count_fields(self) -> None:
        path = Path("fixture.json")
        obj = validator.load_profile(validator.default_profile_paths()[0])
        obj = copy.deepcopy(obj)
        obj["spark_count"] = 3
        errors = validator.validate_profile(obj, path)
        self.assertTrue(any("fixed Spark count" in item for item in errors))

    def test_rejects_secret_looking_endpoint_keys(self) -> None:
        path = Path("fixture.json")
        fixture = [item for item in validator.default_profile_paths() if item.name == "qwen_local_provider.example.json"][0]
        obj = validator.load_profile(fixture)
        obj = copy.deepcopy(obj)
        obj["endpoint"]["api_key"] = "sk-not-real"
        errors = validator.validate_profile(obj, path)
        self.assertTrue(any("secret-looking" in item for item in errors))

    def test_production_eligible_requires_measured_output(self) -> None:
        path = Path("fixture.json")
        obj = validator.load_profile(validator.default_profile_paths()[0])
        obj = copy.deepcopy(obj)
        obj["production_eligible"] = True
        obj["measured_output_tps"] = None
        obj["last_probe_artifact"] = "fixtures/probe.json"
        errors = validator.validate_profile(obj, path)
        self.assertTrue(any("measured_output_tps" in item for item in errors))

    def test_production_eligible_rejects_blocked_endpoint(self) -> None:
        path = Path("fixture.json")
        fixture = [item for item in validator.default_profile_paths() if item.name == "standard_local_small_openai_compatible.example.json"][0]
        obj = validator.load_profile(fixture)
        obj = copy.deepcopy(obj)
        obj["production_eligible"] = True
        obj["measured_output_tps"] = 1.0
        obj["last_probe_artifact"] = "fixtures/probe.json"
        errors = validator.validate_profile(obj, path)
        self.assertTrue(any("blocked" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
