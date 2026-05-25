from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import AutoRunner, NixlProxyRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.topology import SparkTopology
from ds4_nixl.service import NixlDeployment, nixl_kv_transfer_config, plan_deployment, write_launch_scripts
from ds4_tools.registry import ToolRegistry


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_PATH = ROOT / "profiles" / "nixl" / "qwen27_spark7_nixl.json"


class NixlPlanningTests(unittest.TestCase):
    def test_qwen27_deployment_generates_prefiller_decoder_and_proxy(self) -> None:
        deployment = NixlDeployment.load(DEPLOYMENT_PATH)
        plan = plan_deployment(deployment)

        self.assertEqual(plan["format"], "ds4-nixl-launch-plan-v1")
        self.assertEqual(plan["profile_id"], "qwen3_6_27b_fp8_nixl_experimental_v1")
        self.assertEqual(plan["prefiller"]["spark_node"], "spark7")
        self.assertEqual(plan["decoder"]["spark_node"], "spark7")
        self.assertIn("--kv-transfer-config", plan["prefiller"]["argv"])
        self.assertIn("NixlConnector", plan["prefiller"]["command"])
        self.assertIn("--no-disable-hybrid-kv-cache-manager", plan["prefiller"]["argv"])
        self.assertEqual(plan["prefiller"]["env"]["VLLM_SSM_CONV_STATE_LAYOUT"], "DS")
        self.assertIn("ds4_nixl.proxy", plan["proxy"]["command"])
        self.assertEqual(plan["proxy"]["openai_base_url"], "http://127.0.0.1:8192")

    def test_kv_config_uses_fail_policy_ucx_and_side_channel_port(self) -> None:
        deployment = NixlDeployment.load(DEPLOYMENT_PATH)
        config = nixl_kv_transfer_config(role="kv_both", deployment=deployment, instance=deployment.prefiller)

        self.assertEqual(config["kv_connector"], "NixlConnector")
        self.assertEqual(config["kv_role"], "kv_both")
        self.assertEqual(config["kv_load_failure_policy"], "fail")
        self.assertEqual(config["kv_connector_extra_config"]["backends"], ["UCX"])
        self.assertEqual(config["kv_port"], 5610)

    def test_write_launch_scripts(self) -> None:
        deployment = NixlDeployment.load(DEPLOYMENT_PATH)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = write_launch_scripts(deployment, tmp)
            for name in ("prefiller", "decoder", "proxy"):
                path = Path(manifest["scripts"][name])
                self.assertTrue(path.exists())
                self.assertTrue(path.read_text().startswith("#!/usr/bin/env bash"))
            self.assertTrue((Path(tmp) / "nixl_launch_manifest.json").exists())

    def test_topology_routes_pinned_nixl_profile_to_spark7(self) -> None:
        registry = ProfileRegistry.load(ROOT / "profiles" / "models")
        topology = SparkTopology.load(ROOT / "profiles" / "topology" / "static_sparks.json")
        profile = registry.get("qwen3_6_27b_fp8_nixl_experimental_v1")
        assignment = topology.assign_profile(profile, immediate=False, current_load={})

        self.assertEqual(assignment.node_id, "spark7")
        self.assertEqual(assignment.node_ids, ("spark7",))
        self.assertEqual(topology.estimate_capacity_by_profile()["qwen3_6_27b_fp8_nixl_experimental_v1"], 1)

    def test_profile_can_be_pinned_but_is_not_default_until_calibrated(self) -> None:
        registry = ProfileRegistry.load(ROOT / "profiles" / "models")
        pinned = registry.resolve(
            capability=None,
            chat=True,
            job_class="longmem",
            model_pin={"profile_id": "qwen3_6_27b_fp8_nixl_experimental_v1"},
        )
        self.assertEqual(pinned.backend, "vllm_nixl")

        default = registry.resolve(capability="efficient", chat=True, job_class="summary")
        self.assertNotEqual(default.profile_id, "qwen3_6_27b_fp8_nixl_experimental_v1")

    def test_tool_registry_has_nixl_plan_tool(self) -> None:
        registry = ToolRegistry.load(ROOT / "tools" / "registry.jsonl")
        tool = registry.get("tool:ds4.nixl.plan")
        self.assertEqual(tool.tool_id, "tool:ds4.nixl.plan")
        result = registry.invoke("tool:ds4.nixl.plan", {"deployment": str(DEPLOYMENT_PATH)})

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["plan"]["profile_id"], "qwen3_6_27b_fp8_nixl_experimental_v1")

    def test_auto_runner_selects_nixl_proxy_for_nixl_backend(self) -> None:
        registry = ProfileRegistry.load(ROOT / "profiles" / "models")
        profile = registry.get("qwen3_6_27b_fp8_nixl_experimental_v1")
        raw = {
            "format": "ds4-inference-request-v1",
            "request_id": "req_nixl",
            "capability": None,
            "chat": True,
            "immediate": False,
            "job_class": "longmem",
            "max_output_tokens": 8,
            "thinking_budget_tokens": 0,
            "input": {"messages": [{"role": "user", "content": "hello"}]},
            "output_contract": {"format": "text"},
            "model_pin": {"profile_id": profile.profile_id},
        }
        request = InferenceRequest.from_json(raw)
        runner = AutoRunner(timeout_s=1)

        self.assertIsInstance(runner._nixl, NixlProxyRunner)
        self.assertEqual(request.model_pin["profile_id"], profile.profile_id)

    def test_plan_is_json_serializable(self) -> None:
        deployment = NixlDeployment.load(DEPLOYMENT_PATH)
        json.dumps(plan_deployment(deployment), sort_keys=True)


if __name__ == "__main__":
    unittest.main()
