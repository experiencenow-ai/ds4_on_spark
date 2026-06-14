from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ds4_infer.profiles import ProfileRegistry
from ds4_infer.api import _batch_limits_by_service, _resolve_pipeline_service, _topology_dispatch_cohort_workers, _topology_dispatch_window
from ds4_infer.deployment import deployment_readiness
from ds4_infer.dispatcher_resident import active_resident_service_ids, resident_service_plans
from ds4_infer.pipelines import pipeline_service_batch_limit
from ds4_infer.runners import FakeRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.service import run_requests
from ds4_infer.startup import startup_plan, warm_startup_models
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
KIMI_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_kimi_qwen_gemma_pp13.json"
KIMI27_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_kimi27_code_pp13.json"
QWEN_GEMMA_PP12_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_qwen_gemma_pp12.json"
QWEN_GEMMA_PP12_PLAIN_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_qwen_gemma_pp12_plain.json"
VALIDATION_TASKS = ROOT / "profiles" / "validation" / "xhigh_live_validation_tasks.json"
ALL_SPARKS = tuple(f"spark{index}" for index in range(8))
QWEN_PP = "qwen3_6_27b_bf16_pp8_efficient_v1"
QWEN_BF16KV_PP = "qwen3_6_27b_bf16_pp8_bf16kv_efficient_v1"
DSV4_PP = "dsv4_vllm_mtp_pp8_smartest_v1"
GEMMA12_PP = "gemma4_12b_it_pp8_peer_v1"
GEMMA26_PP = "gemma4_26b_a4b_it_pp8_peer_v1"
GEMMA31_PP = "gemma4_31b_it_pp8_peer_v1"
KIMI_PP13 = "kimi26_pp13_smart_v1"
KIMI27_PP13 = "kimi27_code_pp13_smart_v1"
QWEN_PP13 = "qwen3_6_27b_bf16_pp13_efficient_v1"
GEMMA26_PP13 = "gemma4_26b_a4b_it_pp13_peer_v1"
QWEN_PP12 = "qwen3_6_27b_bf16_pp12_efficient_v1"
GEMMA26_PP12 = "gemma4_26b_a4b_it_pp12_peer_v1"
QWEN_PP12_PLAIN = "qwen3_6_27b_bf16_pp12_plain_efficient_v1"
GEMMA26_PP12_PLAIN = "gemma4_26b_a4b_it_pp12_plain_peer_v1"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
DSV4_KV_PROFILE = ROOT / "profiles" / "kv_cache" / "dsv4_flash_pp8_simple_offload.json"
DSV4_PRODUCTION = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))
DSV4_KV = json.loads(DSV4_KV_PROFILE.read_text(encoding="utf-8"))


def make_request(request_id: str, *, capability: str, job_class: str, chat: bool = False, immediate: bool = False, model_pin: dict[str, str] | None = None) -> InferenceRequest:
    payload = {
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
    if model_pin is not None:
        payload["model_pin"] = model_pin
    return InferenceRequest.from_json(payload)


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


class StaticSparkTopologyTests(unittest.TestCase):
    def test_kimi_qwen_gemma_pp13_topology_uses_all_thirteen_sparks(self) -> None:
        topology = SparkTopology.load(KIMI_TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()

        self.assertEqual(len(topology.nodes), 13)
        self.assertEqual(capacity[KIMI27_PP13], 256)
        self.assertEqual(capacity[QWEN_PP13], 32)
        self.assertEqual(capacity[GEMMA26_PP13], 16)
        self.assertEqual(
            topology.routing_policy["active_resident_service_ids"],
            ["kimi27_pp13", "qwen27_bf16_pp13", "gemma4_26b_a4b_pp13"],
        )
        kimi = topology.pipeline_service_by_id("kimi27_pp13")
        qwen = topology.pipeline_service_by_id("qwen27_bf16_pp13")
        gemma = topology.pipeline_service_by_id("gemma4_26b_a4b_pp13")
        self.assertEqual(kimi.profile_id, KIMI27_PP13)
        self.assertEqual(kimi.model_id, "moonshotai/Kimi-K2.7-Code")
        self.assertEqual(kimi.api_base_url, "http://127.0.0.1:8138")
        self.assertEqual(kimi.service_id, "kimi27_pp13")
        self.assertEqual(kimi.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertEqual(qwen.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertEqual(gemma.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertEqual(kimi.layer_partition, (4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 4))
        self.assertEqual(qwen.layer_partition, (5, 5, 5, 5, 5, 5, 5, 4, 5, 5, 5, 5, 5))
        self.assertEqual(gemma.layer_partition, (2, 2, 3, 3, 2, 3, 2, 2, 2, 2, 3, 2, 2))
        self.assertEqual(kimi.scheduler["dispatch_batch_limit"], 256)
        self.assertEqual(qwen.scheduler["dispatch_batch_limit"], 32)
        self.assertEqual(gemma.scheduler["dispatch_batch_limit"], 16)
        self.assertEqual(kimi.scheduler["queue_depth_target"], 512)
        self.assertEqual(qwen.scheduler["queue_depth_target"], 128)
        self.assertEqual(gemma.scheduler["queue_depth_target"], 64)
        self.assertEqual(kimi.scheduler["refill_low_watermark"], 128)
        self.assertEqual(qwen.scheduler["refill_low_watermark"], 96)
        self.assertEqual(gemma.scheduler["refill_low_watermark"], 48)
        for service in (kimi, qwen, gemma):
            self.assertTrue(service.scheduler["ready_shape_bucketing"])
            self.assertEqual(service.scheduler["ready_shape_lookahead"], 4)
        self.assertEqual(kimi.kv_cache["gpu_memory_utilization"], 0.34)
        self.assertEqual(qwen.kv_cache["gpu_memory_utilization"], 0.25)
        self.assertEqual(gemma.kv_cache["gpu_memory_utilization"], 0.2)
        for service in (kimi, qwen, gemma):
            self.assertEqual(service.entry_node_id, "spark0")
            self.assertEqual(service.node_ids, ("spark0", "spark1", "spark2", "spark3", "spark4", "spark5", "spark6", "spark7", "spark8", "spark9", "sparka", "sparkb", "sparkc"))
            self.assertEqual(service.kv_cache["connector_id"], "lmcache")
            self.assertEqual(service.kv_cache["external_backend"], "lmcache_hma")
            self.assertEqual(service.kv_cache["expected_entry_fraction_per_node"], 1.0 / 13.0)
            self.assertGreater(int(service.kv_cache["kv_cache_memory_bytes"]), 0)
        coordinator = topology.routing_policy["resident_coordinator_defaults"]
        self.assertEqual(topology.routing_policy["resident_service_expectations"]["gpu_utilization_hard_cap"], 0.93)
        self.assertEqual(coordinator["dispatch_window"], 704)
        self.assertEqual(coordinator["dispatch_refill_batch"], 704)
        self.assertEqual(coordinator["dispatch_cohort_workers"], 704)
        self.assertEqual(coordinator["completion_cohort_max"], 256)
        self.assertEqual(coordinator["completion_pp_safe_cohort_max"], 256)
        self.assertEqual(coordinator["completion_chunk_concurrency"], 4)
        self.assertEqual(coordinator["completion_token_budget"], 131072)

    def test_kimi27_pp13_topology_is_dedicated_qualification_service(self) -> None:
        topology = SparkTopology.load(KIMI27_TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()

        self.assertEqual(len(topology.nodes), 13)
        self.assertEqual(capacity[KIMI27_PP13], 256)
        self.assertEqual(topology.routing_policy["active_resident_service_ids"], ["kimi27_pp13"])
        kimi = topology.pipeline_service_by_id("kimi27_pp13")
        self.assertEqual(kimi.profile_id, KIMI27_PP13)
        self.assertEqual(kimi.model_id, "moonshotai/Kimi-K2.7-Code")
        self.assertEqual(topology.routing_policy["pipeline_services"]["kimi27_pp13"]["served_model_name"], "kimi27-code-pp13")
        self.assertEqual(topology.routing_policy["pipeline_services"]["kimi27_pp13"]["api_base_url"], "http://127.0.0.1:8138")
        self.assertEqual(kimi.layer_partition, (4, 4, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 4))
        self.assertEqual(kimi.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertEqual(kimi.scheduler["dispatch_batch_limit"], 256)
        self.assertEqual(kimi.scheduler["queue_depth_target"], 512)
        self.assertEqual(kimi.scheduler["refill_low_watermark"], 128)
        self.assertEqual(kimi.scheduler["vllm_max_num_seqs"], 256)
        self.assertEqual(kimi.entry_node_id, "spark0")
        self.assertEqual(kimi.node_ids, ("spark0", "spark1", "spark2", "spark3", "spark4", "spark5", "spark6", "spark7", "spark8", "spark9", "sparka", "sparkb", "sparkc"))
        self.assertEqual(kimi.kv_cache["connector_id"], "lmcache")
        self.assertEqual(kimi.kv_cache["external_backend"], "lmcache_hma")
        self.assertEqual(kimi.kv_cache["gpu_memory_utilization"], 0.34)
        self.assertEqual(topology.routing_policy["resident_coordinator_defaults"]["dispatch_window"], 512)
        self.assertEqual(topology.routing_policy["resident_coordinator_defaults"]["completion_cohort_max"], 256)
        self.assertEqual(topology.routing_policy["resident_coordinator_defaults"]["completion_pp_safe_cohort_max"], 256)
        self.assertEqual(topology.routing_policy["resident_coordinator_defaults"]["completion_chunk_concurrency"], 4)
        self.assertEqual(_batch_limits_by_service(topology)["kimi27_pp13"], 256)
        self.assertEqual(_topology_dispatch_window(KIMI27_TOPOLOGY), 512)
        self.assertEqual(_topology_dispatch_cohort_workers(KIMI27_TOPOLOGY), 512)

    def test_kimi27_dedicated_readiness_has_gpu_budget(self) -> None:
        topology = SparkTopology.load(KIMI27_TOPOLOGY)
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13"
        try:
            payload = deployment_readiness(
                topology=topology,
                dispatcher_window=560,
                dispatcher_refill_batch=560,
                dispatcher_cohort_workers=560,
                resident_multimodel=True,
            )

            self.assertTrue(payload["ready"])
            self.assertEqual(payload["resident_gpu_memory_utilization"], {"kimi27_pp13": 0.34})
            self.assertEqual(payload["resident_gpu_memory_utilization_sum"], 0.34)
            self.assertEqual(payload["resident_service_targets"], {"kimi27_pp13": 256})
            self.assertEqual(payload["resident_service_queue_depth_targets"], {"kimi27_pp13": 512})
            failed_errors = {item["name"] for item in payload["checks"] if not item["ok"] and item["severity"] == "error"}
            self.assertNotIn("resident_gpu_budget_declared", failed_errors)

            underfilled = deployment_readiness(
                topology=topology,
                dispatcher_window=128,
                dispatcher_refill_batch=128,
                dispatcher_cohort_workers=64,
                resident_multimodel=True,
            )
        finally:
            if old_auto is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = old_auto
            if old_services is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = old_services
        self.assertFalse(underfilled["ready"])
        failed_errors = {item["name"] for item in underfilled["checks"] if not item["ok"] and item["severity"] == "error"}
        self.assertIn("cohort_workers_cover_largest_service", failed_errors)

    def test_kimi_qwen_readiness_counts_fixed_kv_bytes_as_headroom(self) -> None:
        topology = SparkTopology.load(KIMI_TOPOLOGY)
        old_active = os.environ.get("DS4_API_RESIDENT_SERVICE_IDS")
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        os.environ["DS4_API_RESIDENT_SERVICE_IDS"] = "kimi27_pp13,qwen27_bf16_pp13"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13,qwen27_bf16_pp13"
        try:
            payload = deployment_readiness(
                topology=topology,
                dispatcher_window=640,
                dispatcher_refill_batch=640,
                dispatcher_cohort_workers=640,
                resident_multimodel=True,
            )
        finally:
            if old_active is None:
                os.environ.pop("DS4_API_RESIDENT_SERVICE_IDS", None)
            else:
                os.environ["DS4_API_RESIDENT_SERVICE_IDS"] = old_active
            if old_auto is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = old_auto
            if old_services is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = old_services
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["active_resident_service_ids"], ["kimi27_pp13", "qwen27_bf16_pp13"])
        self.assertEqual(payload["resident_gpu_memory_utilization"], {"kimi27_pp13": 0.34, "qwen27_bf16_pp13": 0.25})
        self.assertEqual(payload["resident_service_targets"], {"kimi27_pp13": 256, "qwen27_bf16_pp13": 32})
        self.assertEqual(payload["resident_service_queue_depth_targets"], {"kimi27_pp13": 512, "qwen27_bf16_pp13": 128})
        self.assertAlmostEqual(payload["resident_gpu_memory_utilization_sum"], 0.59)
        self.assertEqual(payload["resident_fixed_kv_cache_memory_bytes"], {"kimi27_pp13": 8589934592, "qwen27_bf16_pp13": 8589934592})
        self.assertEqual(payload["resident_fixed_kv_cache_memory_bytes_sum"], 17179869184)
        kimi = topology.pipeline_service_by_id("kimi27_pp13")
        self.assertEqual(kimi.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertTrue(kimi.scheduler["ready_shape_bucketing"])
        self.assertEqual(kimi.scheduler["ready_shape_lookahead"], 4)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertTrue(checks["first3_gpu_budget_under_hard_cap"]["ok"])
        self.assertEqual(checks["first3_gpu_budget_under_hard_cap"]["details"]["sum"], 0)
        self.assertEqual(checks["first3_gpu_budget_under_hard_cap"]["details"]["percentage_budget_services"], [])

    def test_kimi_qwen_readiness_honors_resident_target_overrides(self) -> None:
        topology = SparkTopology.load(KIMI_TOPOLOGY)
        old_active = os.environ.get("DS4_API_RESIDENT_SERVICE_IDS")
        old_targets = os.environ.get("DS4_API_SERVICE_TARGETS_JSON")
        old_queue_targets = os.environ.get("DS4_API_SERVICE_QUEUE_DEPTH_TARGETS_JSON")
        old_lows = os.environ.get("DS4_API_SERVICE_LOW_WATERMARKS_JSON")
        old_cohorts = os.environ.get("DS4_API_SERVICE_MAX_COHORTS_JSON")
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_auto_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        os.environ["DS4_API_RESIDENT_SERVICE_IDS"] = "kimi27_pp13,qwen27_bf16_pp13"
        os.environ["DS4_API_SERVICE_TARGETS_JSON"] = '{"kimi27_pp13":96,"qwen27_bf16_pp13":32}'
        os.environ["DS4_API_SERVICE_QUEUE_DEPTH_TARGETS_JSON"] = '{"kimi27_pp13":96,"qwen27_bf16_pp13":32}'
        os.environ["DS4_API_SERVICE_LOW_WATERMARKS_JSON"] = '{"kimi27_pp13":84,"qwen27_bf16_pp13":28}'
        os.environ["DS4_API_SERVICE_MAX_COHORTS_JSON"] = '{"kimi27_pp13":96,"qwen27_bf16_pp13":32}'
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13,qwen27_bf16_pp13"
        try:
            payload = deployment_readiness(
                topology=topology,
                dispatcher_window=256,
                dispatcher_refill_batch=256,
                dispatcher_cohort_workers=128,
                resident_multimodel=True,
            )
        finally:
            _restore_env("DS4_API_RESIDENT_SERVICE_IDS", old_active)
            _restore_env("DS4_API_SERVICE_TARGETS_JSON", old_targets)
            _restore_env("DS4_API_SERVICE_QUEUE_DEPTH_TARGETS_JSON", old_queue_targets)
            _restore_env("DS4_API_SERVICE_LOW_WATERMARKS_JSON", old_lows)
            _restore_env("DS4_API_SERVICE_MAX_COHORTS_JSON", old_cohorts)
            _restore_env("DS4_PIPELINE_AUTO_KV_CACHE", old_auto)
            _restore_env("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", old_auto_services)
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["resident_service_targets"], {"kimi27_pp13": 96, "qwen27_bf16_pp13": 32})
        self.assertEqual(payload["resident_service_queue_depth_targets"], {"kimi27_pp13": 96, "qwen27_bf16_pp13": 32})
        self.assertEqual(payload["largest_target_active"], 96)
        self.assertEqual(payload["target_active_sum"], 128)
        self.assertEqual(payload["largest_queue_depth_target"], 96)
        self.assertEqual(payload["queue_depth_target_sum"], 128)

    def test_qwen_gemma_pp12_topology_leaves_sparkc_for_qualification(self) -> None:
        topology = SparkTopology.load(QWEN_GEMMA_PP12_TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()

        self.assertEqual(len(topology.nodes), 12)
        self.assertEqual(capacity[QWEN_PP12], 128)
        self.assertEqual(capacity[GEMMA26_PP12], 128)
        self.assertEqual(
            topology.routing_policy["active_resident_service_ids"],
            ["qwen27_bf16_pp12", "gemma4_26b_a4b_pp12"],
        )
        self.assertNotIn("sparkc", {node.node_id for node in topology.nodes})
        qwen = topology.pipeline_service_by_id("qwen27_bf16_pp12")
        gemma = topology.pipeline_service_by_id("gemma4_26b_a4b_pp12")
        self.assertEqual(qwen.layer_partition, (5, 5, 5, 5, 6, 6, 6, 6, 5, 5, 5, 5))
        self.assertEqual(gemma.layer_partition, (2, 2, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2))
        self.assertEqual(qwen.pipeline_parallel_size, 12)
        self.assertEqual(gemma.pipeline_parallel_size, 12)
        self.assertEqual(qwen.kv_cache["expected_entry_fraction_per_node"], 1.0 / 12.0)
        self.assertEqual(gemma.kv_cache["expected_entry_fraction_per_node"], 1.0 / 12.0)
        self.assertEqual(qwen.scheduler["vllm_max_num_seqs"], 128)
        self.assertEqual(gemma.scheduler["vllm_max_num_seqs"], 128)
        self.assertEqual(qwen.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertEqual(gemma.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertEqual(qwen.scheduler["refill_low_watermark"], 96)
        self.assertEqual(gemma.scheduler["refill_low_watermark"], 96)
        self.assertEqual(
            topology.routing_policy["resident_coordinator_defaults"]["dispatch_window"],
            256,
        )
        self.assertEqual(float(qwen.kv_cache["gpu_memory_utilization"]) + float(gemma.kv_cache["gpu_memory_utilization"]), 0.8)

    def test_qwen_gemma_pp12_plain_topology_disables_external_lmcache(self) -> None:
        topology = SparkTopology.load(QWEN_GEMMA_PP12_PLAIN_TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()

        self.assertEqual(len(topology.nodes), 12)
        self.assertEqual(capacity[QWEN_PP12_PLAIN], 128)
        self.assertEqual(capacity[GEMMA26_PP12_PLAIN], 128)
        self.assertEqual(
            topology.routing_policy["active_resident_service_ids"],
            ["qwen27_bf16_pp12", "gemma4_26b_a4b_pp12"],
        )
        qwen = topology.pipeline_service_by_id("qwen27_bf16_pp12")
        gemma = topology.pipeline_service_by_id("gemma4_26b_a4b_pp12")
        self.assertEqual(qwen.profile_id, QWEN_PP12_PLAIN)
        self.assertEqual(gemma.profile_id, GEMMA26_PP12_PLAIN)
        self.assertEqual(qwen.kv_cache["connector_id"], "none")
        self.assertEqual(gemma.kv_cache["connector_id"], "none")
        self.assertEqual(qwen.kv_cache["external_backend"], "apc_prefix")
        self.assertEqual(gemma.kv_cache["external_backend"], "apc_prefix")
        self.assertEqual(qwen.scheduler["admission_mode"], "resident_multimodel_rolling_refill")
        self.assertEqual(gemma.scheduler["admission_mode"], "resident_multimodel_rolling_refill")

    def test_openai_aliases_follow_active_pp12_topology_and_reject_absent_dsv4(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(QWEN_GEMMA_PP12_TOPOLOGY)

        qwen = _resolve_pipeline_service(topology, registry, {"model": "qwen"})
        gemma = _resolve_pipeline_service(topology, registry, {"model": "gemma"})
        default = _resolve_pipeline_service(topology, registry, {})
        self.assertEqual(qwen.service_id, "qwen27_bf16_pp12")
        self.assertEqual(gemma.service_id, "gemma4_26b_a4b_pp12")
        self.assertEqual(default.service_id, "qwen27_bf16_pp12")
        with self.assertRaisesRegex(ValueError, "not a configured pipeline service"):
            _resolve_pipeline_service(topology, registry, {"model": "dsv4"})

    def test_openai_aliases_follow_active_pp12_plain_topology(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(QWEN_GEMMA_PP12_PLAIN_TOPOLOGY)

        qwen = _resolve_pipeline_service(topology, registry, {"model": "qwen"})
        gemma = _resolve_pipeline_service(topology, registry, {"model": "gemma"})
        default = _resolve_pipeline_service(topology, registry, {})
        self.assertEqual(qwen.service_id, "qwen27_bf16_pp12")
        self.assertEqual(gemma.service_id, "gemma4_26b_a4b_pp12")
        self.assertEqual(default.service_id, "qwen27_bf16_pp12")
        self.assertEqual(qwen.profile_id, QWEN_PP12_PLAIN)
        self.assertEqual(gemma.profile_id, GEMMA26_PP12_PLAIN)

    def test_topology_filter_keeps_candidate_pp13_profiles_out_of_old_defaults(self) -> None:
        old_topology = SparkTopology.load(TOPOLOGY)
        new_topology = SparkTopology.load(KIMI_TOPOLOGY)

        self.assertNotIn(KIMI27_PP13, old_topology.pipeline_profiles)
        self.assertNotIn(QWEN_PP13, old_topology.pipeline_profiles)
        self.assertNotIn(GEMMA26_PP13, old_topology.pipeline_profiles)
        self.assertIn(KIMI27_PP13, new_topology.pipeline_profiles)
        self.assertIn(QWEN_PP13, new_topology.pipeline_profiles)
        self.assertIn(GEMMA26_PP13, new_topology.pipeline_profiles)

    def test_capacity_reflects_dual_pipeline_services(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        capacity = topology.estimate_capacity_by_profile()
        self.assertEqual(capacity[QWEN_PP], 64)
        self.assertEqual(capacity[QWEN_BF16KV_PP], 64)
        self.assertEqual(capacity[GEMMA26_PP], 64)
        self.assertEqual(capacity[DSV4_PP], DSV4_PRODUCTION["max_num_seqs"])
        self.assertNotIn("qwen3_6_27b_fp8_efficient_v1", capacity)
        self.assertNotIn("dsv4_vllm_mtp_smartest_v1", capacity)
        for node in topology.nodes:
            self.assertEqual(set(node.resident_profiles), {QWEN_PP, GEMMA26_PP, DSV4_PP})
        self.assertEqual(
            topology.routing_policy["active_resident_service_ids"],
            ["qwen27_bf16_pp8", "gemma4_26b_a4b_pp8", "dsv4_flash_pp8"],
        )

    def test_first_three_services_declare_external_cache_backends_and_safe_gpu_caps(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        expected = {
            "qwen27_bf16_pp8": ("lmcache_hma", "lmcache", "/home/{node}/ds4_nvme/ds4_lmcache/qwen27_bf16_pp8_fp8kv/p7_8_7_9_9_9_8_7", 0.25),
            "gemma4_26b_a4b_pp8": ("lmcache_hma", "lmcache", "/home/{node}/ds4_nvme/ds4_lmcache/gemma4_26b_a4b_pp8_bf16kv/p3_4_4_4_3_4_4_4", 0.20),
            "dsv4_flash_pp8": ("dsv4_hma", "simple_cpu_offload", "/home/{node}/ds4_nvme/ds4_hma_store/dsv4_flash_pp8/simple_cpu_offload/p4_5_4_7_5_5_7_6", 0.18),
        }

        for service_id, (backend, connector_id, cache_root, gpu_cap) in expected.items():
            kv_cache = topology.pipeline_service_by_id(service_id).kv_cache
            self.assertEqual(kv_cache["external_backend"], backend)
            self.assertEqual(kv_cache["connector_id"], connector_id)
            self.assertEqual(kv_cache["cache_root"], cache_root)
            self.assertEqual(kv_cache["gpu_memory_utilization"], gpu_cap)
            self.assertEqual(kv_cache["sharding"], "pipeline_layers")
        self.assertLessEqual(sum(item[3] for item in expected.values()), 0.85)

    def test_pipeline_scheduler_batch_defaults_follow_model_capacity(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        dsv4 = topology.pipeline_service_by_id("dsv4_flash_pp8")

        for service_id, service in topology.pipeline_services.items():
            if service_id == "dsv4_flash_pp8":
                continue
            self.assertEqual(service.max_batch_size, 64)
            self.assertEqual(service.scheduler["queue_concurrency"], 64)
            self.assertEqual(service.scheduler["vllm_max_num_seqs"], 64)
            self.assertEqual(pipeline_service_batch_limit(service), 64)
        self.assertEqual(dsv4.max_batch_size, DSV4_PRODUCTION["max_num_seqs"])
        self.assertEqual(dsv4.scheduler["queue_concurrency"], DSV4_PRODUCTION["max_num_seqs"])
        self.assertEqual(dsv4.scheduler["vllm_max_num_seqs"], DSV4_PRODUCTION["max_num_seqs"])
        self.assertEqual(dsv4.scheduler["queue_limit"], DSV4_PRODUCTION["queue_limit"])

    def test_pipeline_services_are_all_spark_and_spark0_ingress(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        qwen = topology.pipeline_service_by_id("qwen27_bf16_pp8")
        qwen_bf16kv = topology.pipeline_service_by_id("qwen27_bf16_pp8_bf16kv")
        dsv4 = topology.pipeline_service_by_id("dsv4_flash_pp8")
        gemma31 = topology.pipeline_service_by_id("gemma4_31b_pp8")
        self.assertEqual(qwen.entry_node_id, "spark0")
        self.assertEqual(qwen_bf16kv.entry_node_id, "spark0")
        self.assertEqual(dsv4.entry_node_id, "spark0")
        self.assertEqual(gemma31.entry_node_id, "spark0")
        self.assertEqual(qwen.node_ids, ALL_SPARKS)
        self.assertEqual(qwen_bf16kv.node_ids, ALL_SPARKS)
        self.assertEqual(dsv4.node_ids, ALL_SPARKS)
        self.assertEqual(gemma31.node_ids, ALL_SPARKS)
        self.assertEqual(qwen.compute_domain, "spark-fleet-0")
        self.assertEqual(qwen_bf16kv.compute_domain, "spark-fleet-0")
        self.assertEqual(dsv4.compute_domain, "spark-fleet-0")
        self.assertEqual(gemma31.compute_domain, "spark-fleet-0")
        self.assertEqual(qwen.layer_partition, (7, 8, 7, 9, 9, 9, 8, 7))
        self.assertEqual(qwen_bf16kv.layer_partition, (7, 8, 8, 8, 9, 9, 8, 7))
        self.assertEqual(dsv4.layer_partition, tuple(DSV4_PRODUCTION["layer_partition"]))
        self.assertEqual(gemma31.layer_partition, (8, 8, 8, 8, 7, 7, 7, 7))
        self.assertEqual(qwen.stages()[-1].layer_end, 64)
        self.assertEqual(qwen_bf16kv.stages()[-1].layer_end, 64)
        self.assertEqual(dsv4.stages()[-1].layer_end, 43)
        self.assertEqual(gemma31.stages()[-1].layer_end, 60)

    def test_resident_dispatcher_only_targets_active_services(self) -> None:
        topology = SparkTopology.load(TOPOLOGY)
        active = active_resident_service_ids(topology)
        plans = resident_service_plans(topology, entry_node_id="spark0", default_batch_linger_s=0.0)

        self.assertEqual(active, {"qwen27_bf16_pp8", "gemma4_26b_a4b_pp8", "dsv4_flash_pp8"})
        self.assertEqual(set(plans), active)

    def test_dsv4_kv_profile_binds_cpu_groups_to_static_fabric(self) -> None:
        env = DSV4_KV["extra_env"]

        self.assertEqual(env["GLOO_SOCKET_IFNAME"], "ds4ring0")
        self.assertEqual(env["TP_SOCKET_IFNAME"], "ds4ring0")
        self.assertEqual(env["VLLM_HOST_IP"], "{fabric_ip}")
        self.assertEqual(env["VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR"], "1")
        self.assertEqual(env["VLLM_DS4_PP_TCP_TENSOR_DICT"], "1")
        self.assertEqual(env["VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT"], "0")
        self.assertEqual(env["VLLM_DS4_PP_TCP_BIND_HOST"], "{fabric_ip}")
        self.assertEqual(env["VLLM_DS4_PP_TCP_ADVERTISE_HOST"], "{fabric_ip}")
        self.assertEqual(env["VLLM_DS4_PP_EDGE_RAIL"], "enp")
        self.assertEqual(DSV4_KV["master_addr"], "10.10.100.10")

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
        self.assertEqual(topology.estimate_capacity_by_profile()[GEMMA12_PP], 64)
        promoted = registry.resolve(capability="gemma4", chat=True, job_class="analysis")
        self.assertEqual(promoted.profile_id, GEMMA26_PP)
        pinned = registry.resolve(capability=None, chat=True, job_class="analysis", model_pin={"profile_id": GEMMA12_PP})
        self.assertEqual(pinned.profile_id, GEMMA12_PP)

    def test_gemma26_is_production_smart_but_not_startup_autoload(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.resolve(capability="smart", chat=True, job_class="analysis")
        assignment = topology.assign_profile(profile, immediate=True, current_load={})

        self.assertEqual(profile.profile_id, GEMMA26_PP)
        self.assertTrue(profile.production_eligible)
        self.assertFalse(profile.routing["requires_profile_pin"])
        self.assertFalse(profile.routing["startup_autoload"])
        self.assertEqual(profile.routing["default_for"], ["smart"])
        self.assertEqual(assignment.node_id, "spark0")
        self.assertEqual(assignment.node_ids, ALL_SPARKS)
        self.assertEqual(assignment.service_id, "gemma4_26b_a4b_pp8")
        self.assertEqual(topology.estimate_capacity_by_profile()[GEMMA26_PP], 64)

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

    def test_dsv4_parallel_chat_profiles_salt_identical_payloads(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        for profile_id in ("dsv4_vllm_mtp_pp8_smartest_v1", "dsv4_vllm_mtp_smartest_v1"):
            profile = registry.get(profile_id)
            self.assertEqual(profile.routing.get("chat_cohort_transport"), "parallel_chat_completions")
            self.assertEqual(profile.routing.get("parallel_chat_payload_salt"), "extra_body_request_id")

    def test_pipeline_node_override_supports_six_sparks(self) -> None:
        with patch.dict("os.environ", {"DS4_PIPELINE_NODES": "spark0,spark1,spark2,spark3,spark4,spark5"}):
            topology = SparkTopology.load(TOPOLOGY)
        qwen = topology.pipeline_service_by_id("qwen27_bf16_pp8")
        qwen_bf16kv = topology.pipeline_service_by_id("qwen27_bf16_pp8_bf16kv")
        dsv4 = topology.pipeline_service_by_id("dsv4_flash_pp8")
        gemma31 = topology.pipeline_service_by_id("gemma4_31b_pp8")
        self.assertEqual(topology.topology_id, "static_sparks_2026_05_29_dual_pp_v1_n6")
        self.assertEqual(qwen.node_ids, tuple(f"spark{index}" for index in range(6)))
        self.assertEqual(qwen_bf16kv.node_ids, tuple(f"spark{index}" for index in range(6)))
        self.assertEqual(dsv4.node_ids, tuple(f"spark{index}" for index in range(6)))
        self.assertEqual(gemma31.node_ids, tuple(f"spark{index}" for index in range(6)))
        self.assertEqual(qwen.pipeline_parallel_size, 6)
        self.assertEqual(qwen_bf16kv.pipeline_parallel_size, 6)
        self.assertEqual(dsv4.pipeline_parallel_size, 6)
        self.assertEqual(gemma31.pipeline_parallel_size, 6)
        self.assertEqual(qwen.layer_partition, (11, 11, 11, 11, 10, 10))
        self.assertEqual(qwen_bf16kv.layer_partition, (11, 11, 11, 11, 10, 10))
        self.assertEqual(dsv4.layer_partition, (8, 7, 7, 7, 7, 7))
        self.assertEqual(gemma31.layer_partition, (10, 10, 10, 10, 10, 10))
        self.assertAlmostEqual(qwen.kv_cache["expected_entry_fraction_per_node"], 1.0 / 6)
        self.assertAlmostEqual(qwen_bf16kv.kv_cache["expected_entry_fraction_per_node"], 1.0 / 6)
        self.assertEqual(dsv4.telemetry["expected_stage_count"], 6)
        self.assertEqual(gemma31.telemetry["expected_stage_count"], 6)

    def test_bf16kv_qwen_pipeline_requires_profile_pin(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = registry.get(QWEN_BF16KV_PP)
        assignment = topology.assign_profile(profile, immediate=True, current_load={})

        self.assertFalse(profile.production_eligible)
        self.assertTrue(profile.routing["requires_profile_pin"])
        self.assertEqual(assignment.node_id, "spark0")
        self.assertEqual(assignment.node_ids, ALL_SPARKS)
        self.assertEqual(assignment.service_id, "qwen27_bf16_pp8_bf16kv")
        self.assertEqual(profile.routing["pipeline"]["served_model_name"], "qwen27-bf16-pp8-bf16kv")

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

    def test_dsv4_pp8_requires_profile_pin_but_still_binds_to_pipeline(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        with self.assertRaisesRegex(ValueError, "no production profile"):
            registry.resolve(capability="smartest", chat=True, job_class="tool_chat")
        profile = registry.resolve(capability=None, chat=True, job_class="tool_chat", model_pin={"profile_id": DSV4_PP})
        assignment = topology.assign_profile(profile, immediate=False, current_load={})
        self.assertEqual(profile.profile_id, DSV4_PP)
        self.assertFalse(profile.production_eligible)
        self.assertTrue(profile.routing["requires_profile_pin"])
        self.assertEqual(profile.model_id, "/home/{node}/models/hf/deepseek-ai/DeepSeek-V4-Flash")
        self.assertEqual(assignment.node_id, "spark0")
        self.assertEqual(assignment.node_ids, ALL_SPARKS)
        self.assertEqual(assignment.service_id, "dsv4_flash_pp8")
        self.assertEqual(assignment.compute_domain, "spark-fleet-0")

    def test_run_manifest_records_pipeline_assignments(self) -> None:
        requests = [
            make_request("r0", capability="efficient", job_class="atom_edit"),
            make_request("r1", capability="smartest", job_class="tool_chat", chat=True, model_pin={"profile_id": DSV4_PP}),
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
        self.assertEqual([item["action"] for item in spark0["items"]], ["pipeline_ingress_warm"])
        self.assertEqual([item["service_id"] for item in spark0["items"]], ["qwen27_bf16_pp8"])
        self.assertEqual([item["action"] for item in spark4["items"]], ["pipeline_stage"])
        self.assertEqual(spark4["items"][0]["stage_index"], 4)
        self.assertEqual(spark4["items"][0]["layer_start"], 31)
        self.assertEqual([item["action"] for item in spark7["items"]], ["pipeline_stage"])

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
        self.assertEqual(result["warm_count"], 1)
        self.assertEqual(
            calls,
            [
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
