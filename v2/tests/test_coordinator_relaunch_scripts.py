from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
STOP_SCRIPT = ROOT / "scripts" / "ds4_stop_coordinator_api.py"
RELAUNCH_SCRIPT = ROOT / "scripts" / "ds4_relaunch_coordinator_api.py"


def load_script(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


class CoordinatorRelaunchScriptTests(unittest.TestCase):
    def test_stop_matcher_targets_only_coordinator_commands(self) -> None:
        stop = load_script(STOP_SCRIPT)

        self.assertTrue(stop._is_coordinator_command("python3 -m ds4_infer.api --port 8700"))
        self.assertTrue(stop._is_coordinator_command("bash scripts/ds4_coordinator_api.sh"))
        self.assertFalse(stop._is_coordinator_command("python3 v2/scripts/ds4_stop_coordinator_api.py"))
        self.assertFalse(stop._is_coordinator_command("python3 v2/scripts/ds4_relaunch_coordinator_api.py"))
        self.assertFalse(stop._is_coordinator_command("ssh spark0 pkill -f ds4_infer.api"))

    def test_stop_targets_include_descendants_without_shell_pattern_matching(self) -> None:
        stop = load_script(STOP_SCRIPT)
        rows = [
            stop.ProcessRow(pid=10, ppid=1, command="python3 -m ds4_infer.api --port 8700"),
            stop.ProcessRow(pid=11, ppid=10, command="python3 -c from multiprocessing.resource_tracker import main"),
            stop.ProcessRow(pid=12, ppid=11, command="helper"),
            stop.ProcessRow(pid=20, ppid=1, command="python3 v2/scripts/ds4_stop_coordinator_api.py"),
            stop.ProcessRow(pid=21, ppid=1, command="ssh spark0 pkill -f ds4_infer.api"),
        ]

        targets = stop._coordinator_targets(rows)

        self.assertEqual([row.pid for row in targets], [12, 11, 10])

    def test_relaunch_throughput_profile_sets_safe_cohort_defaults(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults("throughput")

        self.assertEqual(defaults["DS4_PIPELINE_COHORT_COMPLETIONS"], "1")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], "262144")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_BISECT_ON_FAILURE"], "1")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], "512")
        self.assertEqual(defaults["DS4_COMPUTE_LEASE_QUANTUM_S"], "180")
        self.assertEqual(defaults["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], "51539607552")
        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], "512")
        self.assertIn("dsv4_flash_pp8", defaults["DS4_API_BATCH_LIMITS_JSON"])

    def test_relaunch_production_profile_sets_multi_resident_limits(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults("production")

        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], "262144")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], "512")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], "512")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], "2")
        self.assertEqual(defaults["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], "4294967296")
        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], "512")
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], "512")
        self.assertIn('"dsv4_flash_pp8":512', defaults["DS4_API_BATCH_LIMITS_JSON"])

    def test_relaunch_throughput_profile_overlaps_split_chunks(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults("throughput")

        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], "4")

    def test_relaunch_safety_defaults_override_inherited_env(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old = os.environ.get("DS4_API_DISPATCH_KV_CAPACITY_BYTES")
        os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = "0"
        try:
            args = type("Args", (), {"profile": "throughput"})()
            env = relaunch._coordinator_env(args, ROOT)
        finally:
            if old is None:
                os.environ.pop("DS4_API_DISPATCH_KV_CAPACITY_BYTES", None)
            else:
                os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = old
        self.assertEqual(env["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], "51539607552")


if __name__ == "__main__":
    unittest.main()
