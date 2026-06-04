from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
STOP_SCRIPT = ROOT / "scripts" / "ds4_stop_coordinator_api.py"
RELAUNCH_SCRIPT = ROOT / "scripts" / "ds4_relaunch_coordinator_api.py"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
DSV4_PRODUCTION = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))


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

    def test_relaunch_legacy_profile_names_alias_to_bounded_source_defaults(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        resident = relaunch._profile_defaults(DSV4_PRODUCTION["coordinator_profile"])

        for profile_name in ("throughput", "production", "resident128"):
            self.assertEqual(relaunch._profile_defaults(profile_name), resident)

    def test_relaunch_resident128_profile_sets_bounded_feed_defaults(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults(DSV4_PRODUCTION["coordinator_profile"])
        coordinator = DSV4_PRODUCTION["coordinator"]

        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], str(coordinator["dispatch_window"]))
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], str(coordinator["dispatch_refill_batch"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], str(coordinator["completion_cohort_max"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], str(coordinator["completion_token_budget"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], str(coordinator["completion_pp_safe_cohort_max"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], str(coordinator["completion_chunk_concurrency"]))
        self.assertEqual(defaults["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], str(coordinator["dispatch_kv_capacity_bytes"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS"], "1")
        self.assertEqual(json.loads(defaults["DS4_API_BATCH_LIMITS_JSON"])[DSV4_PRODUCTION["service_id"]], DSV4_PRODUCTION["max_num_seqs"])

    def test_relaunch_resident256_profile_widens_feed_without_kv_bloat(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults("resident256")
        coordinator = DSV4_PRODUCTION["coordinator"]

        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], "256")
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], "98304")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], "4")
        self.assertEqual(defaults["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], str(coordinator["dispatch_kv_capacity_bytes"]))
        self.assertEqual(json.loads(defaults["DS4_API_BATCH_LIMITS_JSON"])[DSV4_PRODUCTION["service_id"]], 256)

    def test_relaunch_arg_parser_accepts_resident128_profile(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old_argv = list(sys.argv)
        sys.argv = [str(RELAUNCH_SCRIPT), "--profile", DSV4_PRODUCTION["coordinator_profile"]]
        try:
            args = relaunch._parse_args()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.profile, DSV4_PRODUCTION["coordinator_profile"])

    def test_relaunch_arg_parser_accepts_resident256_profile(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old_argv = list(sys.argv)
        sys.argv = [str(RELAUNCH_SCRIPT), "--profile", "resident256"]
        try:
            args = relaunch._parse_args()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.profile, "resident256")

    def test_relaunch_arg_parser_defaults_to_source_owned_resident128_profile(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old_argv = list(sys.argv)
        sys.argv = [str(RELAUNCH_SCRIPT)]
        try:
            args = relaunch._parse_args()
        finally:
            sys.argv = old_argv

        self.assertEqual(args.profile, DSV4_PRODUCTION["coordinator_profile"])

    def test_relaunch_env_overrides_apply_after_profile_defaults(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        args = type("Args", (), {"profile": "resident256", "env": ["DS4_API_DISPATCH_WINDOW=192", "DS4_TEST_FLAG=yes"]})()

        env = relaunch._coordinator_env(args, ROOT)

        self.assertEqual(env["DS4_API_DISPATCH_WINDOW"], "192")
        self.assertEqual(env["DS4_TEST_FLAG"], "yes")

    def test_relaunch_safety_defaults_override_inherited_env(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old = os.environ.get("DS4_API_DISPATCH_KV_CAPACITY_BYTES")
        os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = "0"
        try:
            args = type("Args", (), {"profile": DSV4_PRODUCTION["coordinator_profile"]})()
            env = relaunch._coordinator_env(args, ROOT)
        finally:
            if old is None:
                os.environ.pop("DS4_API_DISPATCH_KV_CAPACITY_BYTES", None)
            else:
                os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = old
        self.assertEqual(env["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], str(DSV4_PRODUCTION["coordinator"]["dispatch_kv_capacity_bytes"]))


if __name__ == "__main__":
    unittest.main()
