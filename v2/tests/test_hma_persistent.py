from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_hma.service import Dsv4HmaDeployment, hma_kv_transfer_config, plan_deployment, write_launch_scripts
from ds4_hma.state_package import HmaPersistentStore, HmaStatePart
from ds4_hma.vllm_connector import DS4HmaPersistentConnector
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import AutoRunner, HmaPersistentRunner
from ds4_infer.topology import SparkTopology
from ds4_tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_PATH = ROOT / "profiles" / "hma" / "dsv4_hma_persistent.json"


class HmaPersistentTests(unittest.TestCase):
    def test_hma_state_package_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HmaPersistentStore(tmp)
            part = store.write_part("pkg", "compressor_state", b"state-bytes", kind="compressor_state")
            package = store.create_manifest_package(
                model_id="deepseek-v4",
                tokenizer_hash="tok",
                token_ids=[1, 2, 3, 4],
                block_size=16,
                hma_layout="dsv4_hma_mla_sliding_indexer_compressor_v1",
                state_parts=[part],
                metadata={"source": "unit"},
            )
            store.write_package(package)
            loaded = store.lookup_by_token_ids([1, 2, 3, 4])

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.package_id, package.package_id)
            self.assertEqual(loaded.state_parts[0].kind, "compressor_state")
            self.assertEqual(loaded.state_parts[0].sha256, part.sha256)

    def test_hma_state_package_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = HmaPersistentStore(tmp)
            package = store.create_manifest_package(
                model_id="deepseek-ai/DeepSeek-V4-Flash",
                tokenizer_hash="tok",
                token_ids=[1],
                block_size=16,
                hma_layout="dsv4_hma_mla_sliding_indexer_compressor_v1",
                state_parts=[HmaStatePart(part_id="bad", kind="compressor_state", relative_path="../escape", sha256="x", bytes=1)],
            )

            with self.assertRaises(ValueError):
                store.validate_package(package)

    def test_hma_launch_plan_uses_dynamic_hma_connector(self) -> None:
        deployment = Dsv4HmaDeployment.load(DEPLOYMENT_PATH)
        config = hma_kv_transfer_config(deployment)
        plan = plan_deployment(deployment)

        self.assertEqual(config["kv_connector"], "DS4HmaPersistentConnector")
        self.assertEqual(config["kv_connector_module_path"], "ds4_hma.vllm_connector")
        self.assertEqual(config["kv_connector_extra_config"]["ds4_hma_layout"], "dsv4_hma_mla_sliding_indexer_compressor_v1")
        self.assertIn("--no-disable-hybrid-kv-cache-manager", plan["argv"])
        self.assertIn("1048576", plan["argv"])
        self.assertIn("compressed/sliding/indexer/compressor", " ".join(plan["notes"]))
        self.assertIn("--kv-transfer-config", plan["argv"])

    def test_write_hma_launch_script(self) -> None:
        deployment = Dsv4HmaDeployment.load(DEPLOYMENT_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            path = Path(manifest["scripts"]["server"])

            self.assertTrue(path.exists())
            self.assertIn("DS4HmaPersistentConnector", path.read_text())

    def test_hma_profile_remains_pinned_only_and_not_resident_in_dual_pipeline_topology(self) -> None:
        registry = ProfileRegistry.load(ROOT / "profiles" / "models")
        profile = registry.get("dsv4_vllm_hma_persistent_experimental_v1")
        topology = SparkTopology.load(ROOT / "profiles" / "topology" / "static_sparks.json")

        self.assertFalse(profile.production_eligible)
        self.assertEqual(profile.backend, "vllm_hma")
        self.assertEqual(profile.model_id, "deepseek-ai/DeepSeek-V4-Flash")
        with self.assertRaisesRegex(ValueError, "no spark node has resident profile"):
            topology.assign_profile(profile, immediate=False, current_load={})
        self.assertNotIn(profile.profile_id, topology.estimate_capacity_by_profile())
        with self.assertRaisesRegex(ValueError, "no production profile"):
            registry.resolve(capability="smartest", chat=True, job_class="tool_chat")
        pinned = registry.resolve(capability=None, chat=True, job_class="longmem", model_pin={"profile_id": profile.profile_id})
        self.assertEqual(pinned.profile_id, profile.profile_id)

    def test_hma_plan_tool(self) -> None:
        registry = ToolRegistry.load(ROOT / "tools" / "registry.jsonl")
        result = registry.invoke("tool:ds4.hma.plan", {"deployment": str(DEPLOYMENT_PATH)})

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["plan"]["profile_id"], "dsv4_vllm_hma_persistent_experimental_v1")

    def test_hma_connector_imports_without_vllm_and_exposes_hma_method(self) -> None:
        connector = DS4HmaPersistentConnector(_FakeVllmConfig(), role="scheduler", kv_cache_config=_FakeCacheConfig())
        params = connector.request_finished_all_groups(_FakeRequest(), ([1, 2], [3]))[1]

        self.assertIsNotNone(params)
        self.assertEqual(params["ds4_hma_state"], "pending_extractor_hook")

    def test_auto_runner_has_hma_path(self) -> None:
        runner = AutoRunner(timeout_s=1)
        self.assertIsInstance(runner._hma, HmaPersistentRunner)


class _FakeTransferConfig:
    def __init__(self) -> None:
        self.kv_connector_extra_config = {
            "ds4_hma_store_root": tempfile.mkdtemp(),
            "ds4_hma_hard_fail": "False",
            "ds4_hma_tokenizer_hash": "tok",
        }

    def get_from_extra_config(self, key: str, default: object | None = None) -> object | None:
        return self.kv_connector_extra_config.get(key, default)


class _FakeVllmConfig:
    kv_transfer_config = _FakeTransferConfig()


class _FakeCacheConfig:
    block_size = 16


class _FakeRequest:
    request_id = "req"
    prompt_token_ids = [1, 2, 3]


if __name__ == "__main__":
    unittest.main()
