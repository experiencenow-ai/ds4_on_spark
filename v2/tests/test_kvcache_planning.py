from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_kvcache.service import KvCacheDeployment, kv_transfer_config, plan_deployment, write_launch_scripts
from ds4_tools.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "dsv4_spark45_lmcache.json"


class KvCachePlanningTests(unittest.TestCase):
    def test_lmcache_plan_is_single_vllm_instance(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        plan = plan_deployment(deployment)

        self.assertEqual(plan["format"], "ds4-vllm-kv-cache-launch-plan-v1")
        self.assertEqual(plan["profile_id"], "dsv4_vllm_mtp_smartest_v1")
        self.assertEqual(plan["vllm"]["spark_node"], "spark4")
        self.assertEqual(plan["worker_nodes"], ["spark4", "spark5"])
        self.assertEqual(plan["logical_service_count"], 1)
        self.assertEqual(plan["model_instance_count"], 1)
        self.assertEqual(plan["listen_base_url"], "http://0.0.0.0:8000")
        self.assertEqual(plan["openai_base_url"], "http://spark4:8000")
        self.assertIn("--kv-transfer-config", plan["vllm"]["argv"])
        self.assertNotIn("prefiller", plan)
        self.assertNotIn("decoder", plan)
        self.assertNotIn("proxy", plan)

    def test_lmcache_uses_dynamic_connector_and_disk_config(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        config = kv_transfer_config(deployment.connector)

        self.assertEqual(config["kv_connector"], "LMCacheConnectorV1Dynamic")
        self.assertEqual(config["kv_role"], "kv_both")
        self.assertEqual(config["kv_connector_module_path"], "lmcache.integration.vllm.lmcache_connector_v1")
        self.assertEqual(deployment.extra_env["LMCACHE_USE_EXPERIMENTAL"], "True")
        self.assertTrue(deployment.extra_env["LMCACHE_CONFIG_FILE"].endswith("lmcache_dsv4_spark45.yaml"))

    def test_write_launch_scripts(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            install = Path(manifest["scripts"]["install"])
            start = Path(manifest["scripts"]["start_vllm"])
            self.assertTrue(install.exists())
            self.assertTrue(start.exists())
            self.assertIn("pip install --upgrade lmcache", install.read_text())
            self.assertIn("mkdir -p /mnt/nvme/ds4-lmcache/dsv4-spark45", install.read_text())
            self.assertIn("LMCacheConnectorV1Dynamic", start.read_text())
            self.assertTrue((Path(tmp) / "kv_cache_launch_manifest.json").exists())

    def test_kv_cache_is_optional_on_existing_profiles(self) -> None:
        registry = ProfileRegistry.load(ROOT / "profiles" / "models")
        dsv4 = registry.get("dsv4_vllm_mtp_smartest_v1")
        qwen = registry.get("qwen3_6_27b_fp8_efficient_v1")

        self.assertEqual(dsv4.backend, "vllm_mtp")
        self.assertEqual(qwen.backend, "vllm")
        self.assertEqual(dsv4.routing["optional_kv_cache_deployments"], ["profiles/kv_cache/dsv4_spark45_lmcache.json"])
        self.assertNotIn("optional_kv_cache_deployments", qwen.routing)
        self.assertEqual(registry.resolve(capability="smartest", chat=True, job_class="tool_chat").profile_id, dsv4.profile_id)

    def test_tool_registry_has_kvcache_plan_tool(self) -> None:
        registry = ToolRegistry.load(ROOT / "tools" / "registry.jsonl")
        tool = registry.get("tool:ds4.kvcache.plan")
        self.assertEqual(tool.tool_id, "tool:ds4.kvcache.plan")
        result = registry.invoke("tool:ds4.kvcache.plan", {"deployment": str(DEPLOYMENT)})

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["plan"]["profile_id"], "dsv4_vllm_mtp_smartest_v1")

    def test_plan_is_json_serializable(self) -> None:
        json.dumps(plan_deployment(KvCacheDeployment.load(DEPLOYMENT)), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
