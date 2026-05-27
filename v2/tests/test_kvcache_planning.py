from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_kvcache.service import KvCacheDeployment, kv_transfer_config, plan_deployment, write_launch_scripts
from ds4_tools.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT = ROOT / "profiles" / "kv_cache" / "dsv4_spark45_hma_cpu_offload.json"


class KvCachePlanningTests(unittest.TestCase):
    def test_hma_offload_plan_is_single_vllm_instance(self) -> None:
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
        self.assertIn("--no-disable-hybrid-kv-cache-manager", plan["vllm"]["argv"])
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--max-model-len") + 1], "262144")
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--gpu-memory-utilization") + 1], "0.68")
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--max-num-seqs") + 1], "1")
        self.assertEqual(plan["vllm"]["argv"][plan["vllm"]["argv"].index("--max-num-batched-tokens") + 1], "2048")
        self.assertIn("--speculative-config", plan["vllm"]["argv"])
        self.assertIn("--kv-cache-metrics", plan["vllm"]["argv"])
        self.assertNotIn("LMCacheConnectorV1Dynamic", plan["vllm"]["command"])
        self.assertNotIn("prefiller", plan)
        self.assertNotIn("decoder", plan)
        self.assertNotIn("proxy", plan)

    def test_hma_offload_uses_supported_connector(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        config = kv_transfer_config(deployment.connector)

        self.assertEqual(config["kv_connector"], "SimpleCPUOffloadConnector")
        self.assertEqual(config["kv_role"], "kv_both")
        self.assertEqual(config["kv_connector_extra_config"]["spec_name"], "SimpleCPUOffloadingSpec")
        self.assertEqual(config["kv_connector_extra_config"]["cpu_bytes_to_use"], "2147483648")
        self.assertTrue(config["kv_connector_extra_config"]["lazy_offload"])
        self.assertNotIn("kv_connector_module_path", config)
        self.assertNotIn("LMCACHE_USE_EXPERIMENTAL", deployment.extra_env)
        self.assertEqual(deployment.extra_env["VLLM_USE_SIMPLE_KV_OFFLOAD"], "1")
        self.assertEqual(deployment.extra_env["PYTHONHASHSEED"], "0")

    def test_dsv4_lmcache_dynamic_is_rejected_until_hma_supported(self) -> None:
        deployment = json.loads(DEPLOYMENT.read_text())
        deployment["connector"] = {
            "connector_id": "lmcache_dynamic",
            "kv_role": "kv_both",
        }
        with self.assertRaisesRegex(ValueError, "SupportsHMA"):
            KvCacheDeployment.from_json(deployment)

    def test_dsv4_plain_offloading_connector_is_rejected(self) -> None:
        deployment = json.loads(DEPLOYMENT.read_text())
        deployment["connector"] = {
            "connector_id": "offloading",
            "kv_role": "kv_both",
        }
        with self.assertRaisesRegex(ValueError, "SimpleCPUOffloadConnector"):
            KvCacheDeployment.from_json(deployment)

    def test_write_launch_scripts(self) -> None:
        deployment = KvCacheDeployment.load(DEPLOYMENT)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            install = Path(manifest["scripts"]["install"])
            start = Path(manifest["scripts"]["start_vllm"])
            self.assertTrue(install.exists())
            self.assertTrue(start.exists())
            self.assertIn("no connector packages requested", install.read_text())
            self.assertIn("SimpleCPUOffloadConnector", start.read_text())
            self.assertIn("--no-disable-hybrid-kv-cache-manager", start.read_text())
            self.assertNotIn("LMCacheConnectorV1Dynamic", start.read_text())
            self.assertTrue((Path(tmp) / "kv_cache_launch_manifest.json").exists())

    def test_kv_cache_is_optional_on_existing_profiles(self) -> None:
        registry = ProfileRegistry.load(ROOT / "profiles" / "models")
        dsv4 = registry.get("dsv4_vllm_mtp_smartest_v1")
        qwen = registry.get("qwen3_6_27b_fp8_efficient_v1")

        self.assertEqual(dsv4.backend, "vllm_mtp")
        self.assertEqual(qwen.backend, "vllm")
        self.assertEqual(dsv4.routing["optional_kv_cache_deployments"], ["profiles/kv_cache/dsv4_spark45_hma_cpu_offload.json"])
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
