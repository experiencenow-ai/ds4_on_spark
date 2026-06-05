from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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
ALL_SPARKS = tuple(f"spark{index}" for index in range(8))
QWEN_PP = "qwen3_6_27b_bf16_pp8_efficient_v1"
DSV4_PP = "dsv4_vllm_mtp_pp8_smartest_v1"
GEMMA12_PP = "gemma4_12b_it_pp8_peer_v1"
GEMMA31_PP = "gemma4_31b_it_pp8_peer_v1"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
DSV4_PRODUCTION = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))


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
    def test_capacity_reflects_dual_pipeline_services(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()
        self.assertEqual(capacity[QWEN_PP], 12)
        self.assertEqual(capacity[DSV4_PP], DSV4_PRODUCTION["max_num_seqs"])
        self.assertNotIn("qwen3_6_27b_fp8_efficient_v1", capacity)
        self.assertNotIn("dsv4_vllm_mtp_smartest_v1", capacity)

    def test_pipeline_services_are_all_spark_and_spark0_ingress(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        qwen = topology.pipeline_service_by_id("qwen27_bf16_pp8")
        dsv4 = topology.pipeline_service_by_id("dsv4_flash_pp8")
        gemma31 = topology.pipeline_service_by_id("gemma4_31b_pp8")
        self.assertEqual(qwen.entry_node_id, "spark0")
        self.assertEqual(dsv4.entry_node_id, "spark0")
        self.assertEqual(gemma31.entry_node_id, "spark0")
        self.assertEqual(qwen.node_ids, ALL_SPARKS)
        self.assertEqual(dsv4.node_ids, ALL_SPARKS)
        self.assertEqual(gemma31.node_ids, ALL_SPARKS)
        self.assertEqual(qwen.compute_domain, "spark-fleet-0")
        self.assertEqual(dsv4.compute_domain, "spark-fleet-0")
        self.assertEqual(gemma31.compute_domain, "spark-fleet-0")
        self.assertEqual(qwen.layer_partition, (9, 9, 9, 8, 8, 8, 8, 5))
        self.assertEqual(dsv4.layer_partition, tuple(DSV4_PRODUCTION["layer_partition"]))
        self.assertEqual(gemma31.layer_partition, (8, 8, 8, 8, 7, 7, 7, 7))
        self.assertEqual(qwen.stages()[-1].layer_end, 64)
        self.assertEqual(dsv4.stages()[-1].layer_end, 43)
        self.assertEqual(gemma31.stages()[-1].layer_end, 60)

    def test_gemma_pipeline_profiles_are_profile_pin_only(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.get(GEMMA12_PP)
        assignment = topology.assign_profile(profile, immediate=True, current_load={})

        self.assertFalse(profile.production_eligible)
        self.assertTrue(profile.routing["requires_profile_pin"])
        self.assertEqual(assignment.node_id, "spark0")
        self.assertEqual(assignment.node_ids, ALL_SPARKS)
        self.assertEqual(assignment.service_id, "gemma4_12b_pp8")
        self.assertEqual(topology.estimate_capacity_by_profile()[GEMMA12_PP], 16)
        with self.assertRaisesRegex(ValueError, "no production profile"):
            registry.resolve(capability="gemma4", chat=True, job_class="analysis")
        pinned = registry.resolve(capability=None, chat=True, job_class="analysis", model_pin={"profile_id": GEMMA12_PP})
        self.assertEqual(pinned.profile_id, GEMMA12_PP)

    def test_production_chat_profiles_have_authoritative_tokenizer_path(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        missing = [
            profile.profile_id
            for profile in registry.all_profiles()
            if profile.production_eligible
            and profile.supports_chat
            and not profile.routing.get("tokenizer_path")
        ]
        self.assertEqual(missing, [])

    def test_dsv4_chat_profiles_use_source_owned_template_renderer(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        missing = [
            profile.profile_id
            for profile in registry.all_profiles()
            if profile.production_eligible
            and profile.supports_chat
            and profile.model_id == "deepseek-ai/DeepSeek-V4-Flash"
            and profile.routing.get("chat_template_renderer") != "deepseek_v4"
        ]
        self.assertEqual(missing, [])

    def test_pipeline_node_override_supports_six_sparks(self) -> None:
        with patch.dict("os.environ", {"DS4_PIPELINE_NODES": "spark0,spark1,spark2,spark3,spark4,spark5"}):
            topology = SparkTopology.load(TOPOLOGY)
        qwen = topology.pipeline_service_by_id("qwen27_bf16_pp8")
        dsv4 = topology.pipeline_service_by_id("dsv4_flash_pp8")
        gemma31 = topology.pipeline_service_by_id("gemma4_31b_pp8")
        self.assertEqual(topology.topology_id, "static_sparks_2026_05_29_dual_pp_v1_n6")
        self.assertEqual(qwen.node_ids, tuple(f"spark{index}" for index in range(6)))
        self.assertEqual(dsv4.node_ids, tuple(f"spark{index}" for index in range(6)))
        self.assertEqual(gemma31.node_ids, tuple(f"spark{index}" for index in range(6)))
        self.assertEqual(qwen.pipeline_parallel_size, 6)
        self.assertEqual(dsv4.pipeline_parallel_size, 6)
        self.assertEqual(gemma31.pipeline_parallel_size, 6)
        self.assertEqual(qwen.layer_partition, (11, 11, 11, 11, 10, 10))
        self.assertEqual(dsv4.layer_partition, (8, 7, 7, 7, 7, 7))
        self.assertEqual(gemma31.layer_partition, (10, 10, 10, 10, 10, 10))
        self.assertAlmostEqual(qwen.kv_cache["expected_entry_fraction_per_node"], 1.0 / 6)
        self.assertEqual(dsv4.telemetry["expected_stage_count"], 6)
        self.assertEqual(gemma31.telemetry["expected_stage_count"], 6)

    def test_efficient_request_binds_to_qwen_pipeline(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="efficient", chat=False, job_class="atom_edit")
        assignment = topology.assign_profile(profile, immediate=True, current_load={})
        self.assertEqual(profile.profile_id, QWEN_PP)
        self.assertEqual(assignment.node_id, "spark0")
        self.assertEqual(assignment.node_ids, ALL_SPARKS)
        self.assertEqual(assignment.service_id, "qwen27_bf16_pp8")
        self.assertEqual(assignment.reason, "pipeline_service")

    def test_smart_chat_binds_to_dsv4_pipeline(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="smartest", chat=True, job_class="tool_chat")
        assignment = topology.assign_profile(profile, immediate=False, current_load={})
        self.assertEqual(profile.profile_id, DSV4_PP)
        self.assertEqual(profile.model_id, "deepseek-ai/DeepSeek-V4-Flash")
        self.assertEqual(assignment.node_id, "spark0")
        self.assertEqual(assignment.node_ids, ALL_SPARKS)
        self.assertEqual(assignment.service_id, "dsv4_flash_pp8")
        self.assertEqual(assignment.compute_domain, "spark-fleet-0")

    def test_run_manifest_records_pipeline_assignments(self) -> None:
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
            self.assertEqual(manifest["topology_id"], "static_sparks_2026_05_29_dual_pp_v1")
            self.assertEqual(manifest["selected_nodes"], {"spark0": 2})
            self.assertEqual(manifest["selected_services"], {"dsv4_flash_pp8": 1, "qwen27_bf16_pp8": 1})
            responses = [json.loads(line) for line in (Path(tmp) / "responses.jsonl").read_text().splitlines()]
            self.assertEqual(responses[0]["selected_node"]["node_id"], "spark0")
            self.assertEqual(responses[0]["selected_node"]["node_ids"], list(ALL_SPARKS))
            self.assertEqual(responses[1]["selected_node"]["service_id"], "dsv4_flash_pp8")

    def test_static_topology_has_no_dynamic_ejection_lane(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        self.assertFalse(topology.routing_policy.get("allow_dynamic_load_for_unmatched_profiles"))
        self.assertEqual(topology.routing_policy.get("queue_entry_node_id"), "spark0")
        self.assertTrue(topology.routing_policy.get("bind_on_submit"))
        self.assertTrue(all(not node.dynamic_load for node in topology.nodes))
        self.assertTrue(all("pipeline_stage" in node.roles for node in topology.nodes))

    def test_xhigh_live_validation_manifest_lists_pipeline_checks(self) -> None:
        manifest = json.loads(VALIDATION_TASKS.read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "ds4-xhigh-live-validation-tasks-v1")
        task_ids = [task["task_id"] for task in manifest["tasks"]]
        self.assertEqual(
            task_ids,
            [
                "xhv-001-qwen27-bf16-pp8-service",
                "xhv-002-dsv4-flash-pp8-service",
                "xhv-003-single-ingress-queue-submit",
                "xhv-004-shared-compute-domain-scheduler",
                "xhv-005-pipeline-kv-shards",
                "xhv-006-stage-telemetry",
                "xhv-007-non8-pipeline-config",
            ],
        )
        qwen_task = manifest["tasks"][0]
        self.assertEqual(qwen_task["target_nodes"], list(ALL_SPARKS))
        self.assertIn(QWEN_PP, qwen_task["profiles"])

    def test_startup_plan_marks_ingress_and_stage_items(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        spark0 = startup_plan(topology=topology, registry=registry, node_id="spark0")
        spark4 = startup_plan(topology=topology, registry=registry, node_id="spark4")
        spark7 = startup_plan(topology=topology, registry=registry, node_id="spark7")
        self.assertEqual([item["action"] for item in spark0["items"]], ["pipeline_ingress_warm", "pipeline_ingress_warm"])
        self.assertEqual([item["service_id"] for item in spark0["items"]], ["dsv4_flash_pp8", "qwen27_bf16_pp8"])
        self.assertEqual([item["action"] for item in spark4["items"]], ["pipeline_stage", "pipeline_stage"])
        self.assertEqual(spark4["items"][0]["stage_index"], 4)
        self.assertEqual(spark4["items"][1]["layer_start"], 35)
        self.assertEqual([item["action"] for item in spark7["items"]], ["pipeline_stage", "pipeline_stage"])

    def test_startup_warm_posts_only_ingress_items(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        plan = startup_plan(topology=topology, registry=registry, node_id="spark0")
        calls: list[tuple[str, str]] = []

        def poster(url: str, payload: dict, timeout_s: int) -> dict:
            calls.append((url, payload["model"]))
            return {"ok": True}

        result = warm_startup_models(plan=plan, base_url="http://spark.local:8000", timeout_s=3, poster=poster)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["warm_count"], 2)
        self.assertEqual(
            calls,
            [
                ("http://127.0.0.1:8102/v1/chat/completions", "deepseek-ai/DeepSeek-V4-Flash"),
                ("http://127.0.0.1:8101/v1/chat/completions", "Qwen/Qwen3.6-27B"),
            ],
        )

    def test_startup_warm_skips_non_ingress_stage_items(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        plan = startup_plan(topology=topology, registry=registry, node_id="spark6")
        calls: list[tuple[str, str]] = []

        def poster(url: str, payload: dict, timeout_s: int) -> dict:
            calls.append((url, payload["model"]))
            return {"ok": True}

        result = warm_startup_models(plan=plan, base_url="http://spark.local:8000", timeout_s=3, poster=poster)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["warm_count"], 0)
        self.assertEqual(calls, [])
        self.assertEqual({item["status"] for item in result["results"]}, {"skipped"})


if __name__ == "__main__":
    unittest.main()
