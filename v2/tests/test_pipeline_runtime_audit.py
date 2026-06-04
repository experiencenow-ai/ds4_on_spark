from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_pipeline_runtime_audit.py"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = load_script_module("ds4_pipeline_runtime_audit", SCRIPT)


class PipelineRuntimeAuditTests(unittest.TestCase):
    def test_dsv4_production_profile_is_source_of_truth(self) -> None:
        profile = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))

        self.assertEqual(profile["format"], "ds4-production-profile-v1")
        self.assertEqual(sum(profile["layer_partition"]), 43)
        self.assertEqual(len(profile["layer_partition"]), profile["pipeline_parallel_size"])
        self.assertLessEqual(profile["layer_partition"][0], max(profile["layer_partition"][1:]))
        self.assertEqual(profile["max_num_seqs"], profile["coordinator"]["dispatch_window"])
        self.assertEqual(profile["max_num_seqs"], profile["coordinator"]["completion_cohort_max"])
        self.assertEqual(profile["kv_cache_memory_bytes"], profile["coordinator"]["dispatch_kv_capacity_bytes"])
        self.assertFalse(profile["speculative_decode"])
        self.assertTrue((ROOT / profile["runtime_contract"]).exists())
        self.assertTrue((ROOT / profile["kv_deployment"]).exists())
        self.assertTrue((ROOT / profile["topology"]).exists())

    def test_pipeline_runtime_audit_passes_checked_in_profiles(self) -> None:
        self.assertEqual(audit.main(), 0)


if __name__ == "__main__":
    unittest.main()
