from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
STOP_SCRIPT = ROOT / "scripts" / "ds4_stop_coordinator_api.py"
RELAUNCH_SCRIPT = ROOT / "scripts" / "ds4_relaunch_coordinator_api.py"
TOKEN_SCRIPT = ROOT / "scripts" / "ds4_prefetch_token.py"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
DSV4_PRODUCTION = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))
FIRST3_MEMORY_BUDGET_PROFILE = ROOT / "profiles" / "production" / "first3_resident_memory_budget.json"
FIRST3_MEMORY_BUDGET = json.loads(FIRST3_MEMORY_BUDGET_PROFILE.read_text(encoding="utf-8"))
STATIC_SPARKS_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
STATIC_TOPOLOGY = json.loads(STATIC_SPARKS_TOPOLOGY.read_text(encoding="utf-8"))
QWEN_GEMMA_PP12_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_qwen_gemma_pp12.json"
KIMI27_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_kimi27_code_pp13.json"
KIMI_QWEN_GEMMA_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_kimi_qwen_gemma_pp13.json"


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

    def test_relaunch_resident128_profile_sets_first3_feed_defaults(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults(DSV4_PRODUCTION["coordinator_profile"])
        coordinator = FIRST3_MEMORY_BUDGET["coordinator"]

        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], str(coordinator["dispatch_window"]))
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], str(coordinator["dispatch_refill_batch"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], str(coordinator["completion_cohort_max"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], str(coordinator["completion_token_budget"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_BUDGET_INCLUDE_OUTPUT"], "0")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], str(coordinator["completion_pp_safe_cohort_max"]))
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], str(coordinator["completion_chunk_concurrency"]))
        self.assertEqual(defaults["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], str(coordinator["dispatch_kv_capacity_bytes"]))
        self.assertEqual(defaults["DS4_API_DISPATCH_COHORT_WORKERS"], "128")
        self.assertEqual(defaults["DS4_API_RENDER_CHAT_WITH_TOKENIZER"], "1")
        self.assertEqual(defaults["DS4_API_REQUIRE_TOKENIZER_CHAT_RENDER"], "1")
        self.assertEqual(defaults["DS4_API_RESIDENT_MULTIMODEL"], "1")
        self.assertEqual(defaults["DS4_API_RESIDENT_SERVICE_IDS"], "qwen27_bf16_pp8,gemma4_26b_a4b_pp8,dsv4_flash_pp8")
        self.assertEqual(defaults["DS4_API_DEPLOYMENT_STRICT"], "0")
        self.assertEqual(defaults["DS4_API_JIT_KV_RECOVER_ON_STARTUP"], "1")
        self.assertEqual(defaults["DS4_API_JIT_KV_CIRCUIT_BREAKER"], "1")
        self.assertEqual(defaults["DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS"], "1")
        self.assertEqual(defaults["DS4_PIPELINE_SSE_CANCEL_POLL_TIMEOUT_S"], "0.25")
        self.assertEqual(defaults["DS4_PIPELINE_SSE_FIRST_EVENT_TIMEOUT_S"], "60")
        self.assertEqual(defaults["DS4_PIPELINE_SSE_IDLE_TIMEOUT_S"], "30")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS"], "1")
        self.assertEqual(json.loads(defaults["DS4_API_BATCH_LIMITS_JSON"])[DSV4_PRODUCTION["service_id"]], DSV4_PRODUCTION["max_num_seqs"])

    def test_relaunch_batch_limits_come_from_static_topology(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        limits = relaunch._pipeline_batch_limits()
        services = STATIC_TOPOLOGY["routing_policy"]["pipeline_services"]

        self.assertEqual(set(limits), set(services))
        for service_id, service in services.items():
            scheduler = service.get("scheduler", {})
            expected = int(scheduler.get("vllm_max_num_seqs") or service["max_batch_size"])
            self.assertEqual(limits[service_id], expected)
        self.assertNotIn("qwen27_nvfp4_pp8", limits)

    def test_relaunch_pp12_topology_sets_active_services_and_wider_feed(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults(DSV4_PRODUCTION["coordinator_profile"], topology_path=QWEN_GEMMA_PP12_TOPOLOGY)
        limits = json.loads(defaults["DS4_API_BATCH_LIMITS_JSON"])

        self.assertEqual(defaults["DS4_API_RESIDENT_SERVICE_IDS"], "qwen27_bf16_pp12,gemma4_26b_a4b_pp12")
        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], "256")
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], "256")
        self.assertEqual(defaults["DS4_API_DISPATCH_COHORT_WORKERS"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], "131072")
        self.assertEqual(defaults["DS4_API_JIT_KV_PREFETCH_API"], "0")
        self.assertEqual(defaults["DS4_PIPELINE_AUTO_KV_CACHE"], "1")
        self.assertEqual(limits, {"gemma4_26b_a4b_pp12": 128, "qwen27_bf16_pp12": 128})

    def test_relaunch_kimi27_profile_selects_kimi_topology_and_lmcache_auto_kv(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old_argv = list(sys.argv)
        old_prefetch = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        old_auto_kv_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "stale-service"
        sys.argv = [str(RELAUNCH_SCRIPT), "--profile", "kimi27"]
        try:
            args = relaunch._parse_args()
            env = relaunch._coordinator_env(args, ROOT)
        finally:
            sys.argv = old_argv
            if old_prefetch is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch
            if old_auto_kv_services is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = old_auto_kv_services
        defaults = relaunch._profile_defaults(args.profile, topology_path=relaunch._resolve_topology_path(args.topology, ROOT))
        limits = json.loads(defaults["DS4_API_BATCH_LIMITS_JSON"])

        self.assertEqual(args.topology, str(KIMI27_TOPOLOGY.relative_to(ROOT)))
        self.assertEqual(defaults["DS4_API_RESIDENT_SERVICE_IDS"], "kimi27_pp13")
        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], "256")
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], "256")
        self.assertEqual(defaults["DS4_API_DISPATCH_COHORT_WORKERS"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], "128")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], "128")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], "4")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], "65536")
        self.assertEqual(defaults["DS4_API_JIT_KV_PREFETCH_API"], "0")
        self.assertEqual(defaults["DS4_PIPELINE_AUTO_KV_CACHE"], "1")
        self.assertEqual(defaults["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"], "kimi27_pp13")
        self.assertEqual(defaults["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"], "prefer_batch")
        self.assertEqual(limits, {"kimi27_pp13": 128})
        self.assertEqual(env["DS4_API_JIT_KV_PREFETCH_API"], "0")
        self.assertEqual(env["DS4_PIPELINE_AUTO_KV_CACHE"], "1")
        self.assertEqual(env["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"], "kimi27_pp13")
        self.assertEqual(env["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"], "prefer_batch")

    def test_relaunch_centaur_profile_selects_kimi_qwen_gemma_topology(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old_argv = list(sys.argv)
        old_prefetch = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        old_services = os.environ.get("DS4_API_RESIDENT_SERVICE_IDS")
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        os.environ["DS4_API_RESIDENT_SERVICE_IDS"] = "stale-service"
        sys.argv = [str(RELAUNCH_SCRIPT), "--profile", "centaur"]
        try:
            args = relaunch._parse_args()
            env = relaunch._coordinator_env(args, ROOT)
        finally:
            sys.argv = old_argv
            if old_prefetch is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch
            if old_services is None:
                os.environ.pop("DS4_API_RESIDENT_SERVICE_IDS", None)
            else:
                os.environ["DS4_API_RESIDENT_SERVICE_IDS"] = old_services
        defaults = relaunch._profile_defaults(args.profile, topology_path=relaunch._resolve_topology_path(args.topology, ROOT))
        limits = json.loads(defaults["DS4_API_BATCH_LIMITS_JSON"])

        self.assertEqual(args.topology, str(KIMI_QWEN_GEMMA_TOPOLOGY.relative_to(ROOT)))
        self.assertEqual(defaults["DS4_API_RESIDENT_SERVICE_IDS"], "kimi27_pp13,qwen27_bf16_pp13,gemma4_26b_a4b_pp13")
        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], "448")
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], "448")
        self.assertEqual(defaults["DS4_API_DISPATCH_COHORT_WORKERS"], "448")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], "128")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], "65536")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], "128")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], "4")
        self.assertEqual(defaults["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], str(19327352832))
        self.assertEqual(defaults["DS4_API_JIT_KV_PREFETCH_API"], "0")
        self.assertEqual(defaults["DS4_PIPELINE_AUTO_KV_CACHE"], "1")
        self.assertEqual(defaults["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"], "kimi27_pp13,qwen27_bf16_pp13,gemma4_26b_a4b_pp13")
        self.assertEqual(defaults["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"], "prefer_batch")
        self.assertEqual(defaults["DS4_API_RESIDENT_PREFER_COHORT_BATCH"], "1")
        self.assertEqual(defaults["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"], "1")
        self.assertEqual(limits, {"gemma4_26b_a4b_pp13": 16, "kimi27_pp13": 128, "qwen27_bf16_pp13": 16})
        self.assertEqual(env["DS4_API_RESIDENT_SERVICE_IDS"], "kimi27_pp13,qwen27_bf16_pp13,gemma4_26b_a4b_pp13")
        self.assertEqual(env["DS4_API_JIT_KV_PREFETCH_API"], "0")
        self.assertEqual(env["DS4_PIPELINE_AUTO_KV_CACHE"], "1")
        self.assertEqual(env["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"], "prefer_batch")
        self.assertEqual(env["DS4_API_RESIDENT_PREFER_COHORT_BATCH"], "1")
        self.assertEqual(env["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"], "1")

    def test_relaunch_resident256_profile_widens_feed_without_kv_bloat(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)

        defaults = relaunch._profile_defaults("resident256")

        self.assertEqual(defaults["DS4_API_DISPATCH_WINDOW"], "256")
        self.assertEqual(defaults["DS4_API_DISPATCH_REFILL_BATCH"], "256")
        self.assertEqual(defaults["DS4_API_DISPATCH_COHORT_WORKERS"], "192")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_MAX"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET"], "98304")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_COHORT_BUDGET_INCLUDE_OUTPUT"], "0")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX"], "256")
        self.assertEqual(defaults["DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY"], "4")
        self.assertEqual(defaults["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], str(FIRST3_MEMORY_BUDGET["coordinator"]["dispatch_kv_capacity_bytes"]))
        self.assertEqual(json.loads(defaults["DS4_API_BATCH_LIMITS_JSON"])[DSV4_PRODUCTION["service_id"]], DSV4_PRODUCTION["max_num_seqs"])

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

    def test_relaunch_coordinator_python_prefers_explicit_override(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        args = type("Args", (), {"coordinator_python": "/opt/ds4/python"})()

        self.assertEqual(relaunch._coordinator_python(args), "/opt/ds4/python")

    def test_relaunch_coordinator_python_prefers_vllm_runtime_when_present(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "python"
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            args = type("Args", (), {"coordinator_python": ""})()

            self.assertEqual(relaunch._coordinator_python(args, default_path=path), str(path))

    def test_relaunch_coordinator_python_falls_back_locally(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        args = type("Args", (), {"coordinator_python": ""})()

        self.assertEqual(relaunch._coordinator_python(args, default_path=Path("/definitely/missing/ds4-python")), sys.executable)

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
        args = type("Args", (), {
            "profile": "resident256",
            "env": [
                "DS4_API_DISPATCH_WINDOW=192",
                "DS4_TEST_FLAG=yes",
                "DS4_API_JIT_KV_PREFETCH_TOKEN=unit-test-token",
            ],
        })()

        env = relaunch._coordinator_env(args, ROOT)

        self.assertEqual(env["DS4_API_DISPATCH_WINDOW"], "192")
        self.assertEqual(env["DS4_TEST_FLAG"], "yes")

    def test_relaunch_prefetch_api_loads_token_file(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token"
            token_file.write_text("unit-file-token\n", encoding="utf-8")
            args = type("Args", (), {
                "profile": DSV4_PRODUCTION["coordinator_profile"],
                "env": ["DS4_API_JIT_KV_PREFETCH_API=1"],
                "prefetch_token_file": str(token_file),
            })()

            env = relaunch._coordinator_env(args, ROOT)

        self.assertEqual(env["DS4_API_JIT_KV_PREFETCH_TOKEN"], "unit-file-token")

    def test_relaunch_prefetch_token_loader_falls_back_to_second_default_file(self) -> None:
        tokens = load_script(TOKEN_SCRIPT)
        old_files = tokens.DEFAULT_PREFETCH_TOKEN_FILES
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-token"
            fallback = Path(tmp) / "fallback-token"
            fallback.write_text("fallback-value\n", encoding="utf-8")
            tokens.DEFAULT_PREFETCH_TOKEN_FILES = (missing, fallback)
            try:
                token = tokens.load_prefetch_token(str(missing))
            finally:
                tokens.DEFAULT_PREFETCH_TOKEN_FILES = old_files

        self.assertEqual(token, "fallback-value")

    def test_relaunch_safety_defaults_override_inherited_env(self) -> None:
        relaunch = load_script(RELAUNCH_SCRIPT)
        old_kv = os.environ.get("DS4_API_DISPATCH_KV_CAPACITY_BYTES")
        old_resident = os.environ.get("DS4_API_RESIDENT_MULTIMODEL")
        old_services = os.environ.get("DS4_API_RESIDENT_SERVICE_IDS")
        old_auto_kv = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = "0"
        os.environ["DS4_API_RESIDENT_MULTIMODEL"] = "0"
        os.environ["DS4_API_RESIDENT_SERVICE_IDS"] = "all-the-things"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "0"
        try:
            args = type("Args", (), {
                "profile": DSV4_PRODUCTION["coordinator_profile"],
                "env": ["DS4_API_JIT_KV_PREFETCH_TOKEN=unit-test-token"],
            })()
            env = relaunch._coordinator_env(args, ROOT)
        finally:
            if old_kv is None:
                os.environ.pop("DS4_API_DISPATCH_KV_CAPACITY_BYTES", None)
            else:
                os.environ["DS4_API_DISPATCH_KV_CAPACITY_BYTES"] = old_kv
            if old_resident is None:
                os.environ.pop("DS4_API_RESIDENT_MULTIMODEL", None)
            else:
                os.environ["DS4_API_RESIDENT_MULTIMODEL"] = old_resident
            if old_services is None:
                os.environ.pop("DS4_API_RESIDENT_SERVICE_IDS", None)
            else:
                os.environ["DS4_API_RESIDENT_SERVICE_IDS"] = old_services
            if old_auto_kv is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = old_auto_kv
        self.assertEqual(env["DS4_API_DISPATCH_KV_CAPACITY_BYTES"], str(FIRST3_MEMORY_BUDGET["coordinator"]["dispatch_kv_capacity_bytes"]))
        self.assertEqual(env["DS4_API_RESIDENT_MULTIMODEL"], "1")
        self.assertEqual(env["DS4_API_RESIDENT_SERVICE_IDS"], "qwen27_bf16_pp8,gemma4_26b_a4b_pp8,dsv4_flash_pp8")
        self.assertEqual(env["DS4_PIPELINE_AUTO_KV_CACHE"], "1")


if __name__ == "__main__":
    unittest.main()
