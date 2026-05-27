from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.service import run_requests
from ds4_infer.startup import startup_plan, warm_startup_models
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
VALIDATION_TASKS = ROOT / "profiles" / "validation" / "xhigh_live_validation_tasks.json"


def make_request(request_id: str, *, capability: str, job_class: str, chat: bool = False, immediate: bool = False) -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": request_id,
            "capability": capability,
            "chat": chat,
            "immediate": immediate,
            "job_class": job_class,
            "max_output_tokens": 128,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": {"target_atom_id": f"atom:{request_id}", "source_atom_hash": "h"},
            "output_contract": {"format": "centaur-atom-edit-v1", "strict_json": True},
        }
    )


class StaticSparkTopologyTests(unittest.TestCase):
    def test_capacity_reflects_static_allocation(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()
        self.assertEqual(capacity["qwen3_6_27b_fp8_efficient_v1"], 5)
        self.assertNotIn("qwen3_6_35b_a3b_fp8_fastest_v1", capacity)
        self.assertEqual(capacity["dsv4_vllm_mtp_smartest_v1"], 1)
        self.assertNotIn("dsv4_antirez_smart_v1", capacity)

    def test_qwen_requests_spread_across_qwen_lanes_only(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="efficient", chat=False, job_class="atom_edit")
        load: dict[str, int] = {}
        nodes: list[str] = []
        for _ in range(5):
            assignment = topology.assign_profile(profile, immediate=False, current_load=load)
            load[assignment.node_id] = load.get(assignment.node_id, 0) + 1
            nodes.append(assignment.node_id)
        self.assertEqual(sorted(nodes), ["spark0", "spark1", "spark2", "spark3", "spark6"])

    def test_immediate_efficient_request_stays_on_qwen_lanes(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="efficient", chat=False, job_class="atom_edit")
        assignment = topology.assign_profile(profile, immediate=True, current_load={})
        self.assertIn(assignment.node_id, {"spark0", "spark1", "spark2", "spark3", "spark6"})
        self.assertEqual(assignment.reason, "resident_profile")

    def test_vllm_chat_routes_to_dsv4_static_lanes(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="smartest", chat=True, job_class="tool_chat")
        self.assertEqual(profile.model_id, "deepseek-ai/DeepSeek-V4-Flash")
        assignment = topology.assign_profile(profile, immediate=False, current_load={})
        self.assertEqual(assignment.node_id, "spark5")
        self.assertEqual(assignment.node_ids, ("spark4", "spark5"))
        self.assertEqual(assignment.reason, "resident_profile_group")

    def test_run_manifest_records_topology_assignments(self) -> None:
        requests = [
            make_request("r0", capability="efficient", job_class="atom_edit"),
            make_request("r1", capability="smartest", job_class="tool_chat", chat=True),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            manifest = run_requests(
                requests=requests,
                registry=ProfileRegistry.load(PROFILES),
                runner=FakeRunner(),
                out_dir=tmp,
                topology=SparkTopology.load(TOPOLOGY),
            )
            self.assertEqual(manifest["topology_id"], "static_sparks_2026_05_27_v9")
            self.assertEqual(manifest["selected_nodes"]["spark0"], 1)
            self.assertEqual(manifest["selected_nodes"]["spark5"], 1)
            responses = [json.loads(line) for line in (Path(tmp) / "responses.jsonl").read_text().splitlines()]
            self.assertEqual(responses[0]["selected_node"]["node_id"], "spark0")
            self.assertEqual(responses[1]["selected_node"]["node_id"], "spark5")
            self.assertEqual(responses[1]["selected_node"]["node_ids"], ["spark4", "spark5"])

    def test_smart_completion_routes_to_dsv4_group_lane(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="smart", chat=False, job_class="atom_edit")
        assignment = topology.assign_profile(profile, immediate=True, current_load={})
        self.assertEqual(profile.profile_id, "dsv4_vllm_mtp_smartest_v1")
        self.assertEqual(assignment.node_id, "spark5")
        self.assertEqual(assignment.node_ids, ("spark4", "spark5"))
        self.assertEqual(assignment.reason, "resident_profile_group")

    def test_static_topology_has_no_production_ejection_lane(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        self.assertTrue(topology.routing_policy.get("allow_dynamic_load_for_unmatched_profiles"))
        self.assertEqual(topology.routing_policy.get("experimental_node_id"), "spark7")
        production_nodes = [node for node in topology.nodes if "production" in node.roles]
        self.assertTrue(all(not node.dynamic_load for node in production_nodes))
        spark7 = [node for node in topology.nodes if node.node_id == "spark7"][0]
        self.assertTrue(spark7.dynamic_load)
        self.assertEqual(spark7.resident_profiles, ())

    def test_xhigh_live_validation_manifest_lists_required_checks(self) -> None:
        manifest = json.loads(VALIDATION_TASKS.read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "ds4-xhigh-live-validation-tasks-v1")
        task_ids = [task["task_id"] for task in manifest["tasks"]]
        self.assertEqual(
            task_ids,
            [
                "xhv-001-qwen-vllm-resident-lanes",
                "xhv-002-dsv4-vllm-mtp-spark45",
                "xhv-003-spark6-qwen-vllm",
                "xhv-004-mac-studio-ds4-spark-chat",
                "xhv-005-web-tool-playwright-host",
                "xhv-006-dsv4-vllm-hma-kvoffload-spark45",
                "xhv-007-dsv4-hma-persistent-kv-restart-reload",
            ],
        )
        qwen_task = manifest["tasks"][0]
        self.assertEqual(qwen_task["runner"], "vllm")
        self.assertEqual(qwen_task["target_nodes"], ["spark0", "spark1", "spark2", "spark3", "spark6"])
        self.assertIn("qwen3_6_27b_fp8_efficient_v1", qwen_task["profiles"])
        self.assertNotIn("qwen3_6_35b_a3b_fp8_fastest_v1", qwen_task["profiles"])

    def test_startup_plan_warms_resident_models_and_skips_spark7(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        spark0 = startup_plan(topology=topology, registry=registry, node_id="spark0")
        spark4 = startup_plan(topology=topology, registry=registry, node_id="spark4")
        spark5 = startup_plan(topology=topology, registry=registry, node_id="spark5")
        spark6 = startup_plan(topology=topology, registry=registry, node_id="spark6")
        spark7 = startup_plan(topology=topology, registry=registry, node_id="spark7")
        self.assertEqual([item["model_id"] for item in spark0["items"]], ["Qwen/Qwen3.6-27B-FP8"])
        self.assertEqual(spark4["items"][0]["action"], "group_primary_warm")
        self.assertEqual(len(spark4["items"]), 1)
        self.assertEqual(
            spark5["items"],
            [
                {"profile_id": "dsv4_vllm_mtp_smartest_v1", "action": "group_secondary", "primary_node": "spark4"},
            ],
        )
        self.assertEqual([item["model_id"] for item in spark6["items"]], ["Qwen/Qwen3.6-27B-FP8"])
        self.assertEqual(spark7["items"], [])

    def test_startup_warm_posts_only_executable_items(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        plan = startup_plan(topology=topology, registry=registry, node_id="spark0")
        calls: list[tuple[str, str]] = []

        def poster(url: str, payload: dict, timeout_s: int) -> dict:
            calls.append((url, payload["model"]))
            return {"ok": True}

        result = warm_startup_models(plan=plan, base_url="http://spark.local:8000", timeout_s=3, poster=poster)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["warm_count"], 1)
        self.assertEqual(calls[0], ("http://spark.local:8000/v1/chat/completions", "Qwen/Qwen3.6-27B-FP8"))
        self.assertEqual(len(calls), 1)

    def test_startup_warm_posts_to_spark6_qwen_lane(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        plan = startup_plan(topology=topology, registry=registry, node_id="spark6")
        calls: list[tuple[str, str]] = []

        def poster(url: str, payload: dict, timeout_s: int) -> dict:
            calls.append((url, payload["model"]))
            return {"ok": True}

        result = warm_startup_models(plan=plan, base_url="http://spark.local:8000", timeout_s=3, poster=poster)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(calls[0], ("http://spark.local:8000/v1/chat/completions", "Qwen/Qwen3.6-27B-FP8"))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
