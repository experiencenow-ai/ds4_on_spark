from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_pipeline_lifecycle.py"
TOKEN_SCRIPT = ROOT / "scripts" / "ds4_prefetch_token.py"
WARM_SCRIPT = ROOT / "scripts" / "ds4_warm_dsv4_flashinfer_cache.py"
TOPOLOGY = json.loads((ROOT / "profiles" / "topology" / "static_sparks.json").read_text(encoding="utf-8"))


def load_script(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


class PipelineLifecycleScriptTests(unittest.TestCase):
    def test_catalog_resolves_every_topology_service_to_profile_and_deployment(self) -> None:
        lifecycle = load_script(SCRIPT)
        entries = lifecycle._load_entries(str(ROOT / "profiles" / "topology" / "static_sparks.json"), str(ROOT / "profiles" / "models"))

        self.assertEqual({entry["service_id"] for entry in entries}, set(TOPOLOGY["routing_policy"]["pipeline_services"]))
        for entry in entries:
            service_id = entry["service_id"]
            self.assertTrue((ROOT / str(entry["profile_path"])).exists(), service_id)
            self.assertTrue((ROOT / str(entry["deployment_rel"])).exists(), service_id)
            self.assertEqual(entry["node_ids"], TOPOLOGY["routing_policy"]["pipeline_services"][service_id]["node_ids"])
            deployment = entry["deployment"]
            self.assertIn("{node}/src/ds4_on_spark/v2", str(deployment["working_directory"]))
            self.assertIn("{node}/src/ds4_on_spark/v2/src", str(deployment["pythonpath"]))
            self.assertNotIn(str(deployment["python_bin"]), {"python3", "vllm"})
            self.assertNotIn(str(deployment["vllm_bin"]), {"python3", "vllm"})
            self.assertNotEqual(str(deployment["master_addr"]), entry["entry_node_id"])
            service_kv = TOPOLOGY["routing_policy"]["pipeline_services"][service_id].get("kv_cache", {})
            if service_kv.get("connector_id"):
                self.assertEqual(deployment["connector"]["connector_id"], service_kv["connector_id"])
            if service_kv.get("cache_root"):
                self.assertEqual(deployment["cache_directories"][0], service_kv["cache_root"])

    def test_pp12_deployment_batch_caps_match_topology(self) -> None:
        lifecycle = load_script(SCRIPT)
        entries = lifecycle._load_entries(str(ROOT / "profiles" / "topology" / "static_sparks_qwen_gemma_pp12.json"), str(ROOT / "profiles" / "models"))

        caps = {entry["service_id"]: int(entry["service"]["max_batch_size"]) for entry in entries}

        self.assertEqual(caps, {"gemma4_26b_a4b_pp12": 128, "qwen27_bf16_pp12": 128})
        for entry in entries:
            expected = str(entry["service"]["max_batch_size"])
            deployment = entry["deployment"]
            self.assertEqual(int(deployment["max_batch_size"]), int(expected))
            self.assertEqual(deployment["extra_env"]["VLLM_DS4_SCHED_MAX_NEW_REQS_PER_STEP"], expected)

    def test_selector_accepts_service_profile_and_model_ids(self) -> None:
        lifecycle = load_script(SCRIPT)
        entry = {"service_id": "gemma4_12b_pp8", "profile_id": "gemma4_12b_it_pp8_peer_v1", "model_id": "google/gemma-4-12B-it"}

        for selector in (entry["service_id"], entry["profile_id"], entry["model_id"]):
            self.assertEqual(lifecycle._select_entries([entry], selector), [entry])

    def test_relaunch_expands_to_standard_action_sequence(self) -> None:
        lifecycle = load_script(SCRIPT)

        self.assertEqual(lifecycle._expand_actions(["relaunch"]), ["pull", "stop", "write-scripts", "launch", "probe"])

    def test_remote_launch_expands_home_paths_before_quoting(self) -> None:
        lifecycle = load_script(SCRIPT)
        entries = lifecycle._load_entries(str(ROOT / "profiles" / "topology" / "static_sparks.json"), str(ROOT / "profiles" / "models"))
        entry = [item for item in entries if item["service_id"] == "gemma4_12b_pp8"][0]
        args = type("Args", (), {
            "remote_repo": "$HOME/src/ds4_on_spark",
            "launch_root": "$HOME/.cache/ds4_pipeline_lifecycle",
            "log_dir": "$HOME/ds4_logs/pipeline_lifecycle",
            "remote_env": [],
        })()

        script = lifecycle._remote_launch(entry, 0, "spark0", args)

        self.assertIn('launch_dir="${launch_dir/#\\$HOME/$HOME}"', script)
        self.assertIn('log_dir="${log_dir/#\\$HOME/$HOME}"', script)
        self.assertIn('install="$launch_dir/00_install_kv_cache_deps.sh"', script)
        self.assertIn('DS4_NODE_ID=spark0 bash "$install"', script)
        self.assertIn('nohup bash "$script" > "$log"', script)
        self.assertLess(script.index('DS4_NODE_ID=spark0 bash "$install"'), script.index('nohup bash "$script"'))
        self.assertIn('log=%s\\n" "$!" "$log"', script)

    def test_remote_launch_exports_prefetch_env_before_nohup(self) -> None:
        lifecycle = load_script(SCRIPT)
        entry = {
            "service_id": "qwen27_bf16_pp8",
            "deployment_rel": "profiles/kv_cache/qwen27_bf16_pp8_lmcache_hma.json",
        }
        args = type("Args", (), {
            "remote_repo": "$HOME/src/ds4_on_spark",
            "launch_root": "$HOME/.cache/ds4_pipeline_lifecycle",
            "log_dir": "$HOME/ds4_logs/pipeline_lifecycle",
            "remote_env": ["VLLM_DS4_KV_PREFETCH_API=1", "VLLM_DS4_KV_PREFETCH_TOKEN=unit-test-token"],
        })()

        script = lifecycle._remote_launch(entry, 0, "spark0", args)

        self.assertIn("export VLLM_DS4_KV_PREFETCH_API=1", script)
        self.assertIn("export VLLM_DS4_KV_PREFETCH_TOKEN=unit-test-token", script)
        self.assertLess(script.index("export VLLM_DS4_KV_PREFETCH_API=1"), script.index('nohup bash "$script"'))

    def test_remote_launch_auto_injects_declared_prefetch_token_file(self) -> None:
        lifecycle = load_script(SCRIPT)
        entry = {
            "service_id": "dsv4_flash_pp8",
            "deployment_rel": "profiles/kv_cache/dsv4_flash_pp8_simple_offload.json",
            "deployment": {
                "extra_env": {
                    "VLLM_DS4_KV_PREFETCH_API": "1",
                    "VLLM_DS4_KV_PREFETCH_REQUIRE_TOKEN": "1",
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token"
            token_file.write_text("unit-file-token\n", encoding="utf-8")
            args = type("Args", (), {
                "remote_repo": "$HOME/src/ds4_on_spark",
                "launch_root": "$HOME/.cache/ds4_pipeline_lifecycle",
                "log_dir": "$HOME/ds4_logs/pipeline_lifecycle",
                "remote_env": [],
                "prefetch_token_file": str(token_file),
            })()

            script = lifecycle._remote_launch(entry, 0, "spark0", args)

        self.assertIn("export VLLM_DS4_KV_PREFETCH_TOKEN=unit-file-token", script)
        self.assertLess(script.index("export VLLM_DS4_KV_PREFETCH_TOKEN=unit-file-token"), script.index('nohup bash "$script"'))

    def test_remote_vllm_matcher_does_not_match_its_own_python_source(self) -> None:
        lifecycle = load_script(SCRIPT)
        code = lifecycle._remote_vllm_process_code(include_ppid=False)
        scope = {}
        old_n = os.environ.get("N")
        os.environ["N"] = "[]"
        try:
            exec(code.split("\nfor l in", 1)[0], scope)
        finally:
            if old_n is None:
                os.environ.pop("N", None)
            else:
                os.environ["N"] = old_n

        self.assertFalse(scope["is_vllm_serve"]("python3 -c \"return (' -m vllm.entrypoints.cli.main serve ' in cmd)\""))
        self.assertTrue(scope["is_vllm_serve"]("/opt/venv/bin/python -m vllm.entrypoints.cli.main serve google/gemma-4-26B-A4B-it"))
        self.assertTrue(scope["is_vllm_serve"]("/opt/venv/bin/vllm serve google/gemma-4-26B-A4B-it"))

    def test_prefetch_token_loader_falls_back_to_second_default_file(self) -> None:
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

    def test_dsv4_warmup_runner_exports_prefetch_and_compile_caps(self) -> None:
        warm = load_script(WARM_SCRIPT)
        args = type("Args", (), {"prefetch_max_concurrent": 4})()

        env = dict(warm._warmup_remote_env("unit-test-token", args))

        self.assertEqual(env["VLLM_DS4_KV_PREFETCH_API"], "1")
        self.assertEqual(env["VLLM_DS4_KV_PREFETCH_REQUIRE_TOKEN"], "1")
        self.assertEqual(env["VLLM_DS4_KV_PREFETCH_TOKEN"], "unit-test-token")
        self.assertEqual(env["VLLM_DS4_KV_PREFETCH_MAX_CONCURRENT"], "4")
        self.assertEqual(env["DS4_FLASHINFER_JIT_MAX_JOBS"], "1")
        self.assertEqual(env["MAX_JOBS"], "1")
        self.assertEqual(env["CMAKE_BUILD_PARALLEL_LEVEL"], "1")
        self.assertEqual(env["TORCHINDUCTOR_COMPILE_THREADS"], "1")
        self.assertEqual(env["NVCC_THREADS"], "1")
        self.assertEqual(env["VLLM_DS4_DSV4_SPARSE_MLA_PREFILL_BACKEND"], "indexed")
        self.assertEqual(env["VLLM_DS4_DSV4_PP_FLUSH_HC_BOUNDARY"], "1")
        self.assertEqual(env["VLLM_DEEP_GEMM_WARMUP"], "skip")
        self.assertEqual(env["NCCL_IB_DISABLE"], "1")
        self.assertEqual(env["NCCL_SOCKET_IFNAME"], "ds4ring0")
        self.assertEqual(env["NCCL_SOCKET_FAMILY"], "AF_INET")

    def test_dsv4_warmup_runner_stops_peers_and_launches_dsv4_without_probe(self) -> None:
        warm = load_script(WARM_SCRIPT)
        args = type("Args", (), {
            "execute": False,
            "skip_stop_peers": False,
            "skip_fabric_check": True,
            "remote_repo": "$HOME/src/ds4_on_spark",
            "connect_timeout_s": 8,
            "stagger_s": 2.0,
            "prefetch_max_concurrent": 4,
        })()

        plan = warm._plan(args, token="unit-test-token")

        self.assertEqual(len(plan["peer_stop"]), 2)
        self.assertIn("qwen27_bf16_pp8", plan["peer_stop"][0])
        self.assertIn("gemma4_26b_a4b_pp8", plan["peer_stop"][1])
        self.assertIn("stop", plan["dsv4_stop"])
        self.assertIn("write-scripts", plan["dsv4_launch"])
        self.assertIn("launch", plan["dsv4_launch"])
        self.assertNotIn("probe", plan["dsv4_launch"])
        self.assertIn("--remote-env", plan["dsv4_launch"])

    def test_remote_env_requires_valid_key_value_pairs(self) -> None:
        lifecycle = load_script(SCRIPT)

        with self.assertRaisesRegex(ValueError, "KEY=VALUE"):
            lifecycle._parse_remote_env(["VLLM_DS4_KV_PREFETCH_API"])
        with self.assertRaisesRegex(ValueError, "invalid"):
            lifecycle._parse_remote_env(["1BAD=value"])

    def test_probe_result_requires_json_ok_true(self) -> None:
        lifecycle = load_script(SCRIPT)
        good = lifecycle.subprocess.CompletedProcess(["ssh"], 0, stdout='{"ok": true}\n', stderr="")
        bad_http = lifecycle.subprocess.CompletedProcess(["ssh"], 0, stdout='{"ok": false, "error": "down"}\n', stderr="")
        bad_json = lifecycle.subprocess.CompletedProcess(["ssh"], 0, stdout="not json\n", stderr="")

        self.assertTrue(lifecycle._probe_result_ok(good))
        self.assertFalse(lifecycle._probe_result_ok(bad_http))
        self.assertFalse(lifecycle._probe_result_ok(bad_json))

    def test_printed_commands_redact_secret_assignments(self) -> None:
        lifecycle = load_script(SCRIPT)

        redacted = lifecycle._redact_secrets("export VLLM_DS4_KV_PREFETCH_TOKEN=unit-test-token OTHER=1")

        self.assertIn("VLLM_DS4_KV_PREFETCH_TOKEN=<redacted>", redacted)
        self.assertNotIn("unit-test-token", redacted)

    def test_kill_needles_include_service_profile_and_model_names(self) -> None:
        lifecycle = load_script(SCRIPT)
        entries = lifecycle._load_entries(str(ROOT / "profiles" / "topology" / "static_sparks.json"), str(ROOT / "profiles" / "models"))
        entry = [item for item in entries if item["service_id"] == "gemma4_12b_pp8"][0]

        needles = lifecycle._needles(entry)

        self.assertIn("gemma4_12b_pp8", needles)
        self.assertIn("gemma4_12b_it_pp8_peer_v1", needles)
        self.assertIn("gemma-4-12B-it", needles)
        self.assertIn("gemma-4-12b-it-pp8", needles)
        self.assertNotIn("models", needles)
        self.assertNotIn("google", needles)
        self.assertNotIn("spark0", needles)

    def test_remote_kill_collects_matched_process_descendants(self) -> None:
        lifecycle = load_script(SCRIPT)
        entry = {
            "service_id": "gemma4_12b_pp8",
            "profile_id": "gemma4_12b_it_pp8_peer_v1",
            "model_id": "google/gemma-4-12B-it",
            "deployment": {"model_id": "/home/{node}/models/hf/google/gemma-4-12B-it", "served_model_name": "gemma-4-12b-it-pp8"},
        }

        script = lifecycle._remote_kill(entry)

        self.assertIn("pid=,ppid=,args=", script)
        self.assertIn("children.setdefault(ppid,[]).append(pid)", script)
        self.assertIn("stack.extend(children.get(pid,[]))", script)

    def test_remote_status_and_kill_only_match_real_vllm_serve_commands(self) -> None:
        lifecycle = load_script(SCRIPT)
        entry = {
            "service_id": "dsv4_flash_pp8",
            "profile_id": "dsv4_vllm_mtp_pp8_smartest_v1",
            "model_id": "deepseek-ai/DeepSeek-V4-Flash",
            "deployment": {"model_id": "/home/{node}/models/hf/deepseek-ai/DeepSeek-V4-Flash", "served_model_name": "deepseek-v4-flash-pp8", "master_port": 29544},
        }

        status_script = lifecycle._remote_status(entry)
        kill_script = lifecycle._remote_kill(entry)

        self.assertIn("is_vllm_serve", status_script)
        self.assertIn("is_vllm_serve", kill_script)
        self.assertIn("shlex.split(cmd)", status_script)
        self.assertIn("argv[1]==", status_script)
        self.assertIn("vllm.entrypoints.cli.main", status_script)
        self.assertIn("endswith", kill_script)
        self.assertNotIn("('vllm' in cmd or '--pipeline-parallel-size' in cmd)", kill_script)
        self.assertNotIn("('vllm' in p[1] or '--pipeline-parallel-size' in p[1])", status_script)

    def test_probe_code_polls_until_timeout_deadline(self) -> None:
        lifecycle = load_script(SCRIPT)

        code = lifecycle._remote_probe_code()

        self.assertIn("deadline=time.time()+max", code)
        self.assertIn("while True:", code)
        self.assertIn("urllib.request.urlopen(u,timeout=max(0.2,min(2.0,remaining)))", code)
        self.assertIn("raise SystemExit(1)", code)

    def test_spark_updater_disables_legacy_runtime_config_path(self) -> None:
        script = (ROOT.parent / "scripts" / "ds4_update_spark_nodes.sh").read_text(encoding="utf-8")

        self.assertIn("--runtime-config is disabled", script)
        self.assertIn("--restart-dsv4 is disabled", script)
        self.assertIn("deprecated spark4/spark5 DSV4 unit install/restart is disabled", script)
        self.assertIn("ds4_pipeline_lifecycle.py --service dsv4_flash_pp8 relaunch --execute", script)


if __name__ == "__main__":
    unittest.main()
