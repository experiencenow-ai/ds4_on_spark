from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds4_pipeline_lifecycle.py"
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
        })()

        script = lifecycle._remote_launch(entry, 0, "spark0", args)

        self.assertIn('launch_dir="${launch_dir/#\\$HOME/$HOME}"', script)
        self.assertIn('log_dir="${log_dir/#\\$HOME/$HOME}"', script)
        self.assertIn('nohup bash "$script" > "$log"', script)
        self.assertIn('log=%s\\n" "$!" "$log"', script)

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

    def test_spark_updater_disables_legacy_runtime_config_path(self) -> None:
        script = (ROOT.parent / "scripts" / "ds4_update_spark_nodes.sh").read_text(encoding="utf-8")

        self.assertIn("--runtime-config is disabled", script)
        self.assertIn("--restart-dsv4 is disabled", script)
        self.assertIn("deprecated spark4/spark5 DSV4 unit install/restart is disabled", script)
        self.assertIn("ds4_pipeline_lifecycle.py --service dsv4_flash_pp8 relaunch --execute", script)


if __name__ == "__main__":
    unittest.main()
