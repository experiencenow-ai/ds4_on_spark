from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

from ds4_infer import api as api_module
from ds4_infer.api import CoordinatorApi, _resolve_profile
from ds4_infer.api_stream import _drain_completion_stream_events, openai_chat_stream_events, openai_completion_stream_events
from ds4_infer.coalesced_groups import plan_compatible_payload_groups
from ds4_infer.jit_kv import JitKvCircuitBreaker, run_prefetch
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runner_payloads import AUTO_KV_PRESTAGE_PLAN_KEY
from ds4_infer.runners import OpenAICompatibleRunner, PipelineOpenAIRunner, _coalesced_completion_payload, _maybe_prestage_common_kv_prefix, _openai_payload
from ds4_infer.schemas import InferenceRequest, make_result
from ds4_infer.topology import SparkTopology

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks.json"
KIMI27_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_kimi27_code_pp13.json"
KIMI_QWEN_TOPOLOGY = ROOT / "profiles" / "topology" / "static_sparks_kimi_qwen_pp13.json"
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"
DSV4_PRODUCTION = json.loads(DSV4_PRODUCTION_PROFILE.read_text(encoding="utf-8"))


class PipelineApiTests(unittest.TestCase):
    def test_default_sync_timeout_is_benchmark_safe(self) -> None:
        original = os.environ.pop("DS4_API_SYNC_TIMEOUT_S", None)
        try:
            self.assertGreaterEqual(api_module._default_sync_timeout_s(), 3600.0)
        finally:
            if original is not None:
                os.environ["DS4_API_SYNC_TIMEOUT_S"] = original

    def test_pipeline_openai_payload_uses_served_model_name(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "served-name",
                "capability": "smartest",
                "chat": False,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 8,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"text": "ping"},
                "output_contract": {"format": "text"},
            }
        )
        self.assertEqual(_openai_payload(request, profile)["model"], "deepseek-v4-flash-pp8")

    def test_qwen_pipeline_openai_payload_uses_live_served_model_name(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "qwen-served-name",
                "capability": "efficient",
                "chat": False,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 8,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"text": "ping"},
                "output_contract": {"format": "text"},
            }
        )
        self.assertEqual(_openai_payload(request, profile)["model"], "qwen27-bf16-pp8")

    def test_gemma_alias_resolves_to_profile_pinned_pipeline(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        topology = SparkTopology.load(TOPOLOGY)
        profile = _resolve_profile(registry, topology, "gemma12")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "gemma-served-name",
                "capability": None,
                "chat": True,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 8,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"messages": [{"role": "user", "content": "ping"}]},
                "output_contract": {"format": "text"},
            }
        )
        assignment = topology.assign_profile(profile, immediate=True, current_load={})
        self.assertEqual(profile.profile_id, "gemma4_12b_it_pp8_peer_v1")
        self.assertEqual(assignment.service_id, "gemma4_12b_pp8")
        self.assertEqual(_openai_payload(request, profile)["model"], "gemma-4-12b-it-pp8")

    def test_model_pins_accept_resident_service_aliases(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        self.assertEqual(registry.get("kimi27_pp13").profile_id, "kimi27_code_pp13_smart_v1")
        self.assertEqual(registry.get("qwen27_bf16_pp13").profile_id, "qwen3_6_27b_bf16_pp13_efficient_v1")
        self.assertEqual(registry.get("gemma4_26b_a4b_pp13").profile_id, "gemma4_26b_a4b_it_pp13_peer_v1")
        profile = registry.resolve(capability=None, chat=True, job_class="analysis", model_pin={"profile_id": "kimi27_pp13"})
        self.assertEqual(profile.profile_id, "kimi27_code_pp13_smart_v1")

    def test_pipeline_openai_payload_uses_shared_thinking_fields(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "thinking-payload",
                "capability": "efficient",
                "chat": True,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 64,
                "thinking_budget_tokens": 100,
                "temperature": 0,
                "input": {"messages": [{"role": "user", "content": "solve"}]},
                "output_contract": {"format": "text"},
            }
        )
        payload = _openai_payload(request, profile)
        self.assertEqual(payload["max_tokens"], 164)
        self.assertEqual(payload["thinking"]["budget_tokens"], 100)
        self.assertEqual(payload["thinking_budget_tokens"], 100)
        self.assertEqual(payload["thinking_token_budget"], 100)
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": True})
        self.assertNotIn("extra_body", payload)

    def test_kimi27_pipeline_payload_uses_thinking_budget_and_lmcache_auto_kv(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("kimi27_code_pp13_smart_v1")
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13"
        try:
            request = InferenceRequest.from_json(
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": "kimi27-thinking-payload",
                    "capability": None,
                    "chat": True,
                    "immediate": False,
                    "job_class": "analysis",
                    "max_output_tokens": 4096,
                    "thinking_budget_tokens": 1024,
                    "temperature": 0,
                    "input": {"messages": [{"role": "user", "content": "solve"}]},
                    "output_contract": {"format": "text"},
                    "model_pin": {"profile_id": profile.profile_id},
                }
            )
            payload = _openai_payload(request, profile)
        finally:
            if old_auto is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = old_auto
            if old_services is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = old_services
        self.assertEqual(payload["model"], "kimi27-code-pp13")
        self.assertEqual(payload["max_tokens"], 5120)
        self.assertEqual(payload["thinking"]["budget_tokens"], 1024)
        self.assertEqual(payload["thinking_budget_tokens"], 1024)
        self.assertEqual(payload["thinking_token_budget"], 1024)
        self.assertEqual(payload["chat_template_kwargs"], {"thinking": True})
        self.assertEqual(payload["extra_body"]["ds4_kv_cache"]["backend"], "lmcache")
        self.assertEqual(payload["extra_body"]["ds4_kv_cache"]["model_fingerprint"]["service_id"], "kimi27_pp13")

    def test_kimi27_chat_request_uses_builtin_renderer_without_tokenizer(self) -> None:
        old = os.environ.get("DS4_API_RENDER_CHAT_WITH_TOKENIZER")
        os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=KIMI27_TOPOLOGY, runner_kind="fake")
                api.handle_post(
                    "/v1/chat/completions",
                    {
                        "model": "kimi27",
                        "messages": [{"role": "user", "content": "hello"}],
                        "thinking_budget_tokens": 0,
                        "ds4_async": True,
                        "batch_id": "kimi-rendered-chat",
                    },
                )
                with api.queue._connect() as conn:
                    row = conn.execute("select request_json from requests where batch_id=?", ("kimi-rendered-chat",)).fetchone()
                request_json = json.loads(str(row["request_json"]))
        finally:
            if old is None:
                os.environ.pop("DS4_API_RENDER_CHAT_WITH_TOKENIZER", None)
            else:
                os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = old
        prompt = request_json["input"]["rendered_prompt"]
        self.assertIn("<|im_user|>user<|im_middle|>hello<|im_end|>", prompt)
        self.assertTrue(prompt.endswith("<|im_assistant|>assistant<|im_middle|><think></think>"))
        self.assertEqual(request_json["input"]["prompt"], prompt)

    def test_kimi27_chat_request_renders_thinking_prompt(self) -> None:
        old = os.environ.get("DS4_API_RENDER_CHAT_WITH_TOKENIZER")
        os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=KIMI27_TOPOLOGY, runner_kind="fake")
                api.handle_post(
                    "/v1/chat/completions",
                    {
                        "model": "kimi27",
                        "messages": [{"role": "user", "content": "solve"}],
                        "thinking_budget_tokens": 128,
                        "ds4_async": True,
                        "batch_id": "kimi-thinking-chat",
                    },
                )
                with api.queue._connect() as conn:
                    row = conn.execute("select request_json from requests where batch_id=?", ("kimi-thinking-chat",)).fetchone()
                request_json = json.loads(str(row["request_json"]))
        finally:
            if old is None:
                os.environ.pop("DS4_API_RENDER_CHAT_WITH_TOKENIZER", None)
            else:
                os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = old
        self.assertTrue(request_json["input"]["rendered_prompt"].endswith("<|im_assistant|>assistant<|im_middle|><think>"))

    def test_kimi27_chat_request_chunks_attached_files_into_prompt_context(self) -> None:
        old = os.environ.get("DS4_API_RENDER_CHAT_WITH_TOKENIZER")
        os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=KIMI27_TOPOLOGY, runner_kind="fake")
                status, _payload = api.handle_post(
                    "/v1/chat/completions",
                    {
                        "model": "kimi27",
                        "messages": [{"role": "user", "content": "Which attachment mentions needle?"}],
                        "attachments": [
                            {"name": "alpha.txt", "content": "alpha line\n" * 120},
                            {"filename": "needle.txt", "text": "needle line\n" * 120},
                        ],
                        "ds4_attachment_chunk_tokens": 16,
                        "ds4_attachment_context_budget_tokens": 80,
                        "thinking_budget_tokens": 0,
                        "ds4_async": True,
                        "batch_id": "kimi-attachment-chat",
                    },
                )
                self.assertEqual(status, 202)
                with api.queue._connect() as conn:
                    row = conn.execute("select request_json from requests where batch_id=?", ("kimi-attachment-chat",)).fetchone()
                request_json = json.loads(str(row["request_json"]))
        finally:
            if old is None:
                os.environ.pop("DS4_API_RENDER_CHAT_WITH_TOKENIZER", None)
            else:
                os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = old
        manifest = request_json["input"]["metadata"]["attachment_context"]
        self.assertEqual(manifest["format"], "ds4-attachment-context-v1")
        self.assertEqual(manifest["attachment_count"], 2)
        self.assertGreater(manifest["chunk_count"], manifest["included_chunk_count"])
        self.assertGreater(manifest["omitted_chunk_count"], 0)
        self.assertEqual(manifest["selection"], "query_relevant")
        prompt = request_json["input"]["rendered_prompt"]
        self.assertIn("Attachment manifest:", prompt)
        self.assertIn("needle.txt", prompt)
        self.assertIn("needle line", prompt)
        self.assertIn("Which attachment mentions needle?", prompt)

    def test_dsv4_openai_payload_defaults_chat_template_thinking_off(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "dsv4-thinking-default",
                "capability": "smartest",
                "chat": True,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 64,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"messages": [{"role": "user", "content": "What is 2+2?"}]},
                "output_contract": {"format": "text"},
            }
        )
        payload = _openai_payload(request, profile)
        self.assertEqual(payload["chat_template_kwargs"], {"thinking": False})
        self.assertNotIn("thinking", payload)
        self.assertNotIn("extra_body", payload)

    def test_dsv4_openai_payload_enables_thinking_with_budget(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "dsv4-thinking-budget",
                "capability": "smartest",
                "chat": True,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 64,
                "thinking_budget_tokens": 100,
                "temperature": 0,
                "input": {"messages": [{"role": "user", "content": "What is 2+2?"}]},
                "output_contract": {"format": "text"},
            }
        )
        payload = _openai_payload(request, profile)
        self.assertEqual(payload["max_tokens"], 164)
        self.assertEqual(payload["chat_template_kwargs"], {"thinking": True})
        self.assertEqual(payload["thinking"], {"type": "enabled", "budget_tokens": 100})
        self.assertEqual(payload["thinking_budget_tokens"], 100)

    def test_dsv4_chat_request_uses_source_owned_template_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            api.handle_post(
                "/v1/chat/completions",
                {
                    "model": "deepseek-ai/DeepSeek-V4-Flash",
                    "messages": [
                        {"role": "system", "content": "SYS"},
                        {"role": "user", "content": "USER"},
                    ],
                    "max_tokens": 8,
                    "ds4_async": True,
                    "batch_id": "dsv4-render-chat",
                },
            )
            with api.queue._connect() as conn:
                row = conn.execute("select request_json from requests where batch_id=?", ("dsv4-render-chat",)).fetchone()
            request_json = json.loads(str(row["request_json"]))
        self.assertEqual(
            request_json["input"]["rendered_prompt"],
            "<｜begin▁of▁sentence｜>SYS<｜User｜>USER<｜Assistant｜></think>",
        )

    def test_pipeline_chat_payload_keeps_template_fields_on_chat_body(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "rendered-chat-payload",
                "capability": "efficient",
                "chat": True,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 64,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"messages": [{"role": "user", "content": "solve"}], "rendered_prompt": "<chat>solve</chat>"},
                "output_contract": {"format": "text"},
            }
        )
        payload = _openai_payload(request, profile)
        self.assertNotIn("prompt", payload)
        self.assertEqual(payload["messages"], [{"role": "user", "content": "solve"}])
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("extra_body", payload)

    def test_pipeline_served_model_override_can_key_by_service_id(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "served-name-pp7",
                "capability": "smartest",
                "chat": False,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 8,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"text": "ping"},
                "output_contract": {"format": "text"},
            }
        )
        old = os.environ.get("DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON")
        os.environ["DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON"] = '{"dsv4_flash_pp8":"deepseek-v4-flash-pp7"}'
        try:
            payload = _openai_payload(request, profile)
        finally:
            if old is None:
                os.environ.pop("DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON", None)
            else:
                os.environ["DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON"] = old
        self.assertEqual(payload["model"], "deepseek-v4-flash-pp7")

    def test_pipeline_node_override_rewrites_served_model_pp_suffix(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        request = InferenceRequest.from_json(
            {
                "format": "ds4-inference-request-v1",
                "request_id": "served-name-pp7",
                "capability": "smartest",
                "chat": False,
                "immediate": False,
                "job_class": "analysis",
                "max_output_tokens": 8,
                "thinking_budget_tokens": 0,
                "temperature": 0,
                "input": {"text": "ping"},
                "output_contract": {"format": "text"},
            }
        )
        old_nodes = os.environ.get("DS4_PIPELINE_NODES")
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX")
        os.environ["DS4_PIPELINE_NODES"] = "spark0,spark1,spark2,spark3,spark4,spark5,spark6"
        os.environ.pop("DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX", None)
        try:
            payload = _openai_payload(request, profile)
        finally:
            if old_nodes is None:
                os.environ.pop("DS4_PIPELINE_NODES", None)
            else:
                os.environ["DS4_PIPELINE_NODES"] = old_nodes
            if old_auto is None:
                os.environ.pop("DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX"] = old_auto
        self.assertEqual(payload["model"], "deepseek-v4-flash-pp7")

    def test_submit_binds_to_spark0_pipeline_and_kv_shards_are_layer_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            code, payload = api.handle_post(
                "/ds4/queue/submit",
                {
                    "batch_id": "wm-smoke",
                    "requests": [
                        {
                            "format": "ds4-inference-request-v1",
                            "request_id": "wm-0001",
                            "capability": "efficient",
                            "chat": False,
                            "immediate": False,
                            "job_class": "world_model_extract",
                            "max_output_tokens": 16,
                            "thinking_budget_tokens": 0,
                            "temperature": 0,
                            "input": {"text": "event"},
                            "metadata": {"kv_cache_key": "wm:0001", "kv_bytes_estimate": 8192},
                            "output_contract": {"format": "json", "strict_json": True},
                        }
                    ],
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(payload["selected_nodes"], {"spark0": 1})
            self.assertEqual(payload["selected_services"], {"qwen27_bf16_pp8": 1})

            topology = SparkTopology.load(TOPOLOGY)
            prepared = api.queue.prepare_ready(
                node_id="spark0",
                eligible_profile_ids=tuple(topology.pipeline_profiles),
                batch_id="wm-smoke",
                limit=1,
                leased_by="test",
                lease_ttl_s=30,
                kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
            )
            self.assertEqual(prepared, 1)
            code, status = api.handle_get("/ds4/pipelines", {})
            self.assertEqual(code, 200)
            spark7 = next(shard for shard in status["queue"]["kv_shards"] if shard["service_id"] == "qwen27_bf16_pp8" and shard["node_id"] == "spark7")
            self.assertEqual(spark7["bytes"], 1024)
            self.assertEqual((spark7["layer_start"], spark7["layer_end"]), (57, 64))

    def test_telemetry_report_can_be_stage_shorthand_and_is_completed_from_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            code, result = api.handle_post(
                "/ds4/pipeline/telemetry",
                {
                    "service_id": "dsv4_flash_pp8",
                    "node_id": "spark4",
                    "state": "prod",
                    "metrics": {"decode_tok_s": 4.5},
                },
            )
            self.assertEqual(code, 200)
            self.assertEqual(result["stage_index"], 4)
            code, status = api.handle_get("/ds4/pipelines", {})
            self.assertEqual(code, 200)
            stage = status["queue"]["stages"][0]
            self.assertEqual(stage["service_id"], "dsv4_flash_pp8")
            self.assertEqual(stage["node_id"], "spark4")
            expected_start = sum(DSV4_PRODUCTION["layer_partition"][:4])
            expected_count = DSV4_PRODUCTION["layer_partition"][4]
            self.assertEqual((stage["layer_start"], stage["layer_end"], stage["layer_count"]), (expected_start, expected_start + expected_count, expected_count))

    def test_queue_status_filters_stale_pipeline_status_to_current_topology(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=KIMI_QWEN_TOPOLOGY, runner_kind="fake")
            api.queue.report_pipeline_telemetry(service_id="dsv4_flash_pp8", node_id="spark2", stage_index=2, stage_count=8, payload={"last_gpu_util_pct": 96.0}, reported_at=100.0)
            api.queue.report_pipeline_telemetry(service_id="kimi27_pp13", node_id="spark0", stage_index=0, stage_count=13, payload={"last_gpu_util_pct": 0.0}, reported_at=200.0)

            code, status = api.handle_get("/ds4/queue/status", {})
            self.assertEqual(code, 200)
            stages = status["pipeline_status"]["stages"]
            self.assertEqual([stage["service_id"] for stage in stages], ["kimi27_pp13"])
            self.assertEqual(stages[0]["payload"]["last_gpu_util_pct"], 0.0)

            code, full = api.handle_get("/ds4/pipelines", {})
            self.assertEqual(code, 200)
            self.assertEqual([stage["service_id"] for stage in full["queue"]["stages"]], ["dsv4_flash_pp8", "kimi27_pp13"])

    def test_pipeline_worker_refills_under_existing_compute_lease(self) -> None:
        class Runner:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def run_one_on_node(self, request, profile, node_id):
                self.calls.append(request.request_id)
                return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=request.request_id, status="completed")

        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            requests = [
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": f"pipe-{idx}",
                    "capability": "efficient",
                    "chat": False,
                    "immediate": False,
                    "job_class": "world_model_extract",
                    "max_output_tokens": 16,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"text": f"event {idx}"},
                    "output_contract": {"format": "text"},
                }
                for idx in range(5)
            ]
            code, payload = api.handle_post("/ds4/queue/submit", {"batch_id": "pipe-refill", "requests": requests})
            self.assertEqual(code, 200)
            self.assertEqual(payload["selected_services"], {"qwen27_bf16_pp8": 5})
            topology = SparkTopology.load(TOPOLOGY)
            runner = Runner()
            worked = api.queue.work(
                registry=ProfileRegistry.load(PROFILES),
                runner=runner,
                node_id="spark0",
                batch_id="pipe-refill",
                limit=2,
                concurrency=2,
                node_profile_ids=tuple(topology.pipeline_profiles),
                kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                batch_limits_by_service={"qwen27_bf16_pp8": 2},
                refill_low_watermarks_by_service={"qwen27_bf16_pp8": 1},
            )
            self.assertEqual(worked["batch_dispatch_mode"], "rolling_refill")
            self.assertEqual(worked["claimed_count"], 5)
            self.assertEqual(worked["completed_count"], 5)
            self.assertEqual(api.queue.status(batch_id="pipe-refill")["state"], "completed")
            self.assertEqual(sorted(runner.calls), [f"pipe-{idx}" for idx in range(5)])

    def test_openai_completion_stream_emits_completed_choices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            events = list(
                openai_completion_stream_events(
                    api,
                    {
                        "model": "qwen27_bf16_pp8",
                        "prompt": ["alpha", "beta"],
                        "max_tokens": 7,
                        "stream": True,
                        "ignore_eos": True,
                        "min_tokens": 7,
                    }
                )
            )
        choice_events = sorted((event for event in events if event["choices"]), key=lambda event: event["choices"][0]["index"])
        self.assertEqual([event["choices"][0]["index"] for event in choice_events], [0, 1])
        self.assertEqual([event["choices"][0]["finish_reason"] for event in choice_events], ["stop", "stop"])
        self.assertEqual(events[-1]["choices"], [])
        self.assertEqual(events[-1]["ds4"]["result_count"], 2)

    def test_openai_completion_stream_forwards_delta_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            request = InferenceRequest.from_json(
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": "stream-delta",
                    "chat": False,
                    "immediate": False,
                    "job_class": "analysis",
                    "max_output_tokens": 8,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"prompt": "delta"},
                    "output_contract": {"format": "text"},
                }
            )
            api.queue.stream_delta(request_id="stream-delta", text="tok")
            streamed: set[str] = set()
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            _after, chunks = _drain_completion_stream_events(api, "cmpl", "model", "batch", {"stream-delta": (0, request)}, streamed, usage, 0)
        self.assertEqual(chunks[0]["choices"][0]["text"], "tok")
        self.assertIsNone(chunks[0]["choices"][0]["finish_reason"])
        self.assertEqual(chunks[0]["ds4"]["event_type"], "delta")
        self.assertEqual(streamed, {"stream-delta"})

    def test_openai_chat_request_gets_qwen_builtin_rendered_prompt_for_coalescing(self) -> None:
        old = os.environ.get("DS4_API_RENDER_CHAT_WITH_TOKENIZER")
        os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                api.handle_post(
                    "/v1/chat/completions",
                    {
                        "model": "qwen27_bf16_pp8",
                        "messages": [{"role": "user", "content": "hello"}],
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                        "ds4_async": True,
                        "batch_id": "rendered-chat",
                    },
                )
                with api.queue._connect() as conn:
                    row = conn.execute("select request_json from requests where batch_id=?", ("rendered-chat",)).fetchone()
                request_json = json.loads(str(row["request_json"]))
        finally:
            if old is None:
                os.environ.pop("DS4_API_RENDER_CHAT_WITH_TOKENIZER", None)
            else:
                os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = old
        self.assertEqual(
            request_json["input"]["rendered_prompt"],
            "<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
        )
        self.assertEqual(request_json["input"]["prompt"], request_json["input"]["rendered_prompt"])
        self.assertEqual(request_json["input"]["openai_extra_body"]["chat_template_kwargs"], {"enable_thinking": False})

    def test_openai_chat_request_preserves_explicit_rendered_prompt_for_coalescing(self) -> None:
        old = os.environ.get("DS4_API_RENDER_CHAT_WITH_TOKENIZER")
        os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                api.handle_post(
                    "/v1/chat/completions",
                    {
                        "model": "qwen27_bf16_pp8",
                        "messages": [{"role": "user", "content": "hello"}],
                        "rendered_prompt": "<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n",
                        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
                        "ds4_async": True,
                        "batch_id": "rendered-chat",
                    },
                )
                with api.queue._connect() as conn:
                    row = conn.execute("select request_json from requests where batch_id=?", ("rendered-chat",)).fetchone()
                request_json = json.loads(str(row["request_json"]))
        finally:
            if old is None:
                os.environ.pop("DS4_API_RENDER_CHAT_WITH_TOKENIZER", None)
            else:
                os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = old
        self.assertIn("<|im_start|>user\nhello<|im_end|>", request_json["input"]["rendered_prompt"])
        self.assertEqual(request_json["input"]["prompt"], request_json["input"]["rendered_prompt"])
        self.assertEqual(request_json["input"]["openai_extra_body"]["chat_template_kwargs"], {"enable_thinking": False})

    def test_openai_chat_stream_emits_queue_completion(self) -> None:
        old = os.environ.get("DS4_API_RENDER_CHAT_WITH_TOKENIZER")
        os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                events = list(
                    openai_chat_stream_events(
                        api,
                        {
                            "model": "qwen27_bf16_pp8",
                            "messages": [{"role": "user", "content": "hello"}],
                            "rendered_prompt": "<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n",
                            "max_tokens": 8,
                            "stream": True,
                        },
                    )
                )
        finally:
            if old is None:
                os.environ.pop("DS4_API_RENDER_CHAT_WITH_TOKENIZER", None)
            else:
                os.environ["DS4_API_RENDER_CHAT_WITH_TOKENIZER"] = old
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["object"], "chat.completion.chunk")
        self.assertIn("fake response", events[0]["choices"][0]["delta"]["content"])
        self.assertEqual(events[-1]["choices"][0]["finish_reason"], "stop")

    def test_openai_api_preserves_thinking_budget_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
            api.handle_post(
                "/v1/chat/completions",
                {
                    "model": "qwen27_bf16_pp8",
                    "messages": [{"role": "user", "content": "hello"}],
                    "rendered_prompt": "<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n",
                    "max_tokens": 8,
                    "thinking_budget_tokens": 123,
                    "ds4_async": True,
                    "batch_id": "thinking-chat",
                },
            )
            with api.queue._connect() as conn:
                row = conn.execute("select request_json from requests where batch_id=?", ("thinking-chat",)).fetchone()
            request_json = json.loads(str(row["request_json"]))
        self.assertEqual(request_json["thinking_budget_tokens"], 123)

    def test_dispatcher_pending_claim_count_uses_unfinished_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY)
            registry = ProfileRegistry.load(PROFILES)
            topology = SparkTopology.load(TOPOLOGY)
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"pending-{idx}",
                        "capability": "efficient",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"prompt {idx}"},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            api.queue.submit_requests(requests=requests, registry=registry, topology=topology, batch_id="pending-count")
            prepared = api.queue.prepare_ready(
                node_id="spark0",
                eligible_profile_ids=tuple(topology.pipeline_profiles),
                batch_id="pending-count",
                limit=2,
                leased_by="test",
                lease_ttl_s=30,
                kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
            )
            self.assertEqual(prepared, 2)
            claims = api.queue.claim_ready_batch(
                node_id="spark0",
                batch_id="pending-count",
                limit=2,
                leased_by="test",
                lease_ttl_s=30,
                kv_shard_layouts_by_profile=dict(topology.pipeline_profiles),
                batch_limits_by_service=api_module._batch_limits_by_service(topology),
            )
            cohort = api_module.PendingDispatcherCohort.from_claims(claims)
            self.assertEqual(api_module._pending_claim_count({object(): cohort}), 2)
            first = claims[0]
            api.queue.finish_request(
                request_id=first.request_id,
                lease_id=first.lease_id,
                state="completed",
                result=make_result(
                    request=first.request,
                    profile_id=first.selected_profile_id,
                    model_id="test",
                    backend="test",
                    text="done",
                ),
            )
            cohort.mark_finished(first.request_id)
            self.assertEqual(api_module._pending_claim_count({object(): cohort}), 1)

    def test_deployment_readiness_is_strict_about_jit_kv_token(self) -> None:
        old_strict = os.environ.get("DS4_API_DEPLOYMENT_STRICT")
        old_token = os.environ.get("DS4_API_JIT_KV_PREFETCH_TOKEN")
        old_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        os.environ["DS4_API_DEPLOYMENT_STRICT"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "qwen27_bf16_pp8,gemma4_26b_a4b_pp8,dsv4_flash_pp8"
        os.environ.pop("DS4_API_JIT_KV_PREFETCH_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=TOPOLOGY, runner_kind="fake")
                code, payload = api.handle_get("/ds4/deployment/readiness", {})
        finally:
            if old_strict is None:
                os.environ.pop("DS4_API_DEPLOYMENT_STRICT", None)
            else:
                os.environ["DS4_API_DEPLOYMENT_STRICT"] = old_strict
            if old_token is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_TOKEN", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_TOKEN"] = old_token
            if old_api is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_api
            if old_auto is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = old_auto
            if old_services is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = old_services
        self.assertEqual(code, 503)
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["active_resident_service_ids"], ["dsv4_flash_pp8", "gemma4_26b_a4b_pp8", "qwen27_bf16_pp8"])
        self.assertEqual(
            payload["resident_kv_backends"],
            {"dsv4_flash_pp8": "dsv4_hma", "gemma4_26b_a4b_pp8": "lmcache_hma", "qwen27_bf16_pp8": "lmcache_hma"},
        )
        self.assertEqual(
            payload["resident_kv_connectors"],
            {"dsv4_flash_pp8": "simple_cpu_offload", "gemma4_26b_a4b_pp8": "lmcache", "qwen27_bf16_pp8": "lmcache"},
        )
        self.assertEqual(payload["resident_gpu_memory_utilization"], {"dsv4_flash_pp8": 0.18, "gemma4_26b_a4b_pp8": 0.20, "qwen27_bf16_pp8": 0.25})
        self.assertAlmostEqual(payload["resident_gpu_memory_utilization_sum"], 0.63)
        failed = {item["name"] for item in payload["checks"] if not item["ok"] and item["severity"] == "error"}
        self.assertIn("jit_kv_prefetch_token_present", failed)
        self.assertNotIn("first3_gpu_budget_under_hard_cap", failed)
        passing = {item["name"] for item in payload["checks"] if item["ok"]}
        self.assertIn("dsv4_flash_pp8:external_kv_backend_expected", passing)
        self.assertIn("dsv4_gpu_budget_below_no_headroom_startup_point", passing)

    def test_deployment_readiness_fails_when_external_kv_auto_plans_are_disabled(self) -> None:
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        old_prefetch = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        old_token = os.environ.get("DS4_API_JIT_KV_PREFETCH_TOKEN")
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "0"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "0"
        os.environ.pop("DS4_API_JIT_KV_PREFETCH_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                api = CoordinatorApi(queue_dir=tmp, profiles_dir=PROFILES, topology_path=KIMI27_TOPOLOGY, runner_kind="fake")
                code, payload = api.handle_get("/ds4/deployment/readiness", {})
        finally:
            if old_auto is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = old_auto
            if old_services is None:
                os.environ.pop("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", None)
            else:
                os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = old_services
            if old_prefetch is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch
            if old_token is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_TOKEN", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_TOKEN"] = old_token
        self.assertEqual(code, 503)
        self.assertFalse(payload["ready"])
        failed = {item["name"] for item in payload["checks"] if not item["ok"] and item["severity"] == "error"}
        self.assertIn("external_kv_auto_plan_enabled", failed)
        passing = {item["name"] for item in payload["checks"] if item["ok"]}
        self.assertIn("jit_kv_prefetch_gate_enabled", passing)
        self.assertIn("jit_kv_prefetch_token_present", passing)

    def test_pipeline_runner_prestages_common_strict_kv_prefix(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("qwen3_6_27b_bf16_pp8_efficient_v1")
        prefix = "stable shared prefix " * 80
        plan = {
            "format": "ds4-kv-cache-plan-v1",
            "backend": "simple_cpu_offload",
            "cache_id": "bench-prefix",
            "prefix_hash": "sha256:prefix",
            "load": {"mode": "require", "transport": "local_store"},
            "store": {"mode": "skip", "transport": "none"},
            "miss_policy": "fail",
            "route_affinity": "required",
            "model_fingerprint": {},
            "operation": "load",
            "batch_key_hash": "sha256:batch",
        }
        requests = [
            InferenceRequest.from_json(
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": f"kv-{idx}",
                    "capability": "efficient",
                    "chat": False,
                    "immediate": False,
                    "job_class": "analysis",
                    "max_output_tokens": 8,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"prompt": f"{prefix}request {idx}", "kv_cache_plan": plan},
                    "output_contract": {"format": "text"},
                }
            )
            for idx in range(3)
        ]
        calls: list[dict] = []
        original = OpenAICompatibleRunner._post_json

        def fake_post(self, endpoint, payload, **kwargs):
            calls.append({"endpoint": endpoint, "payload": payload})
            if isinstance(payload.get("prompt"), list):
                return {
                    "choices": [{"index": idx, "text": f"answer {idx}"} for idx in range(3)],
                    "usage": {"prompt_tokens": 30, "completion_tokens": 24, "total_tokens": 54},
                }
            return {"choices": [{"index": 0, "text": "warm"}], "usage": {"completion_tokens": 1}}

        try:
            OpenAICompatibleRunner._post_json = fake_post
            runner = PipelineOpenAIRunner(base_urls={"qwen3_6_27b_bf16_pp8_efficient_v1": "http://127.0.0.1:9"})
            results = runner.run_many_on_node(requests, profile, "spark0", concurrency=3)
        finally:
            OpenAICompatibleRunner._post_json = original
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["payload"]["prompt"], prefix + "request ")
        self.assertEqual(calls[0]["payload"]["extra_body"]["ds4_kv_cache"], plan)
        self.assertEqual(calls[1]["payload"]["prompt"], [f"{prefix}request {idx}" for idx in range(3)])
        self.assertEqual(results["kv-0"]["transport"]["kv_prestage"]["strategy"], "single-prefix-load-before-cohort")

    def test_pipeline_runner_prestages_generated_auto_kv_prefix_fail_open(self) -> None:
        old_prestage_auto = os.environ.get("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX")
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "0"
        try:
            prefix = "stable generated auto prefix " * 50
            plan = {
                "format": "ds4-kv-cache-plan-v1",
                "backend": "lmcache_hma",
                "cache_id": "ds4-auto:qwen27:abc123",
                "prefix_hash": "sha256:auto",
                "load": {"mode": "prefer", "transport": "local_store", "cache_key": "ds4-auto:qwen27:abc123"},
                "store": {"mode": "write_back", "transport": "local_store", "cache_key": "ds4-auto:qwen27:abc123"},
                "miss_policy": "compute_and_store",
                "route_affinity": "preferred",
                "model_fingerprint": {},
                "operation": "load_store",
                "batch_key_hash": "sha256:batch",
            }
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"auto-kv-{idx}",
                        "capability": "efficient",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"{prefix}request {idx}", "shared_prefix": prefix},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            payload = {"model": "qwen27-bf16-pp13", "prompt": [request.input["prompt"] for request in requests], "extra_body": {"ds4_kv_cache": dict(plan)}, "kv_transfer_params": {"ds4_kv_cache": dict(plan)}}
            calls: list[dict] = []
            runner = OpenAICompatibleRunner(base_url="http://127.0.0.1:9")

            def fake_post(endpoint, body, **kwargs):
                calls.append({"endpoint": endpoint, "payload": body})
                return {"choices": [{"index": 0, "text": "warm"}], "usage": {"completion_tokens": 1}}

            runner._post_json = fake_post  # type: ignore[method-assign]
            info = _maybe_prestage_common_kv_prefix(runner, payload, requests)

            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(info["strategy"], "single-prefix-load-before-cohort")
            self.assertEqual(calls[0]["payload"]["prompt"], prefix)
            self.assertIn("kv_transfer_params", payload)
            self.assertIn("extra_body", payload)
        finally:
            if old_prestage_auto is None:
                os.environ.pop("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", None)
            else:
                os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = old_prestage_auto
            if old_prefetch_api is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch_api

    def test_coalesced_completion_prestages_suppressed_auto_kv_prefix(self) -> None:
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        old_policy = os.environ.get("DS4_PIPELINE_AUTO_KV_BATCH_POLICY")
        old_prestage = os.environ.get("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX")
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13"
        os.environ["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"] = "prefer_batch"
        os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "0"
        try:
            registry = ProfileRegistry.load(PROFILES)
            profile = registry.get("kimi27_code_pp13_smart_v1")
            prefix = "batch-compatible automatic prestage prefix " * 40
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"auto-cohort-{idx}",
                        "capability": "smart",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"{prefix}tail {idx}", "shared_prefix": prefix},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            payload = _coalesced_completion_payload(requests, profile, {})
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertNotIn("kv_transfer_params", payload)
            self.assertNotIn("ds4_kv_cache", dict(payload.get("extra_body") or {}))

            calls: list[dict] = []
            runner = OpenAICompatibleRunner(base_url="http://127.0.0.1:9")

            def fake_post(endpoint, body, **kwargs):
                calls.append({"endpoint": endpoint, "payload": body})
                return {"choices": [{"index": 0, "text": "warm"}], "usage": {"completion_tokens": 1}}

            runner._post_json = fake_post  # type: ignore[method-assign]
            info = _maybe_prestage_common_kv_prefix(runner, payload, requests)

            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(info["strategy"], "single-prefix-load-before-cohort")
            self.assertEqual(calls[0]["payload"]["prompt"], prefix)
            plan = calls[0]["payload"]["extra_body"]["ds4_kv_cache"]
            self.assertTrue(plan["cache_id"].startswith("ds4-auto:prefix:kimi27_pp13:"))
            self.assertTrue(info["adopted_for_batch"])
            self.assertEqual(payload["extra_body"]["ds4_kv_cache"], plan)
            self.assertEqual(payload["kv_transfer_params"]["ds4_kv_cache"], plan)
        finally:
            for name, old in (
                ("DS4_PIPELINE_AUTO_KV_CACHE", old_auto),
                ("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", old_services),
                ("DS4_PIPELINE_AUTO_KV_BATCH_POLICY", old_policy),
                ("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", old_prestage),
                ("DS4_API_JIT_KV_PREFETCH_API", old_prefetch_api),
            ):
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old

    def test_generated_auto_kv_prefetch_failure_does_not_attach_hidden_prestage_plan(self) -> None:
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        old_policy = os.environ.get("DS4_PIPELINE_AUTO_KV_BATCH_POLICY")
        old_prestage = os.environ.get("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX")
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13"
        os.environ["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"] = "prefer_batch"
        os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        try:
            registry = ProfileRegistry.load(PROFILES)
            profile = registry.get("kimi27_code_pp13_smart_v1")
            prefix = "failed automatic prestage prefix " * 40
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"auto-fail-hidden-{idx}",
                        "capability": "smart",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"{prefix}tail {idx}", "shared_prefix": prefix},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            payload = _coalesced_completion_payload(requests, profile, {})
            self.assertIsNotNone(payload)
            assert payload is not None
            runner = OpenAICompatibleRunner(base_url="http://127.0.0.1:9")

            def fail_post(endpoint, body, **kwargs):
                raise TimeoutError("prefetch endpoint timed out")

            runner._post_json = fail_post  # type: ignore[method-assign]
            info = _maybe_prestage_common_kv_prefix(runner, payload, requests)

            self.assertIsNotNone(info)
            assert info is not None
            self.assertTrue(info["cold_dispatch"])
            self.assertNotIn("adopted_for_batch", info)
            self.assertNotIn("kv_transfer_params", payload)
            self.assertNotIn("ds4_kv_cache", dict(payload.get("extra_body") or {}))
            self.assertNotIn(AUTO_KV_PRESTAGE_PLAN_KEY, payload)
        finally:
            for name, old in (
                ("DS4_PIPELINE_AUTO_KV_CACHE", old_auto),
                ("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", old_services),
                ("DS4_PIPELINE_AUTO_KV_BATCH_POLICY", old_policy),
                ("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", old_prestage),
                ("DS4_API_JIT_KV_PREFETCH_API", old_prefetch_api),
            ):
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old

    def test_hidden_auto_kv_prestage_plan_does_not_fragment_coalesced_group(self) -> None:
        items = [0, 1, 2, 3]

        def payload_for_chunk(chunk: list[int]) -> dict:
            cache_id = f"ds4-auto:singleton:{chunk[0]}" if len(chunk) == 1 else "ds4-auto:cohort"
            return {
                "model": "kimi27-code-pp13",
                "prompt": [f"common prefix with unique tail {idx}" for idx in chunk],
                "max_tokens": 8,
                AUTO_KV_PRESTAGE_PLAN_KEY: {
                    "cache_id": cache_id,
                    "operation": "load_store",
                },
            }

        planned = plan_compatible_payload_groups(
            items,
            payload_for_chunk=payload_for_chunk,
            chunk_items=lambda group: [group],
            minimum=2,
        )

        self.assertIsNotNone(planned)
        assert planned is not None
        chunks, payloads = planned
        self.assertEqual(chunks, [items])
        self.assertEqual(payloads[0][1][AUTO_KV_PRESTAGE_PLAN_KEY]["cache_id"], "ds4-auto:cohort")
        self.assertEqual(len(payloads[0][1]["prompt"]), 4)

    def test_disabled_common_prestage_clears_hidden_auto_kv_plan(self) -> None:
        old_auto = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE")
        old_services = os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
        old_policy = os.environ.get("DS4_PIPELINE_AUTO_KV_BATCH_POLICY")
        old_prestage_auto = os.environ.get("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX")
        old_prestage_common = os.environ.get("DS4_PIPELINE_PRESTAGE_COMMON_KV_PREFIX")
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE"] = "1"
        os.environ["DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS"] = "kimi27_pp13"
        os.environ["DS4_PIPELINE_AUTO_KV_BATCH_POLICY"] = "prefer_batch"
        os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = "1"
        os.environ["DS4_PIPELINE_PRESTAGE_COMMON_KV_PREFIX"] = "0"
        try:
            registry = ProfileRegistry.load(PROFILES)
            profile = registry.get("kimi27_code_pp13_smart_v1")
            prefix = "disabled common prestage prefix " * 40
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"disabled-prestage-{idx}",
                        "capability": "smart",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"{prefix}tail {idx}", "shared_prefix": prefix},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            payload = _coalesced_completion_payload(requests, profile, {})
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertIn(AUTO_KV_PRESTAGE_PLAN_KEY, payload)
            info = _maybe_prestage_common_kv_prefix(OpenAICompatibleRunner(base_url="http://127.0.0.1:9"), payload, requests)
            self.assertIsNone(info)
            self.assertNotIn(AUTO_KV_PRESTAGE_PLAN_KEY, payload)
            self.assertNotIn("ds4_kv_cache", dict(payload.get("extra_body") or {}))
        finally:
            for name, old in (
                ("DS4_PIPELINE_AUTO_KV_CACHE", old_auto),
                ("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS", old_services),
                ("DS4_PIPELINE_AUTO_KV_BATCH_POLICY", old_policy),
                ("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", old_prestage_auto),
                ("DS4_PIPELINE_PRESTAGE_COMMON_KV_PREFIX", old_prestage_common),
            ):
                if old is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old

    def test_jit_kv_circuit_breaker_dispatches_cold_after_prefetch_failures(self) -> None:
        plan = {
            "format": "ds4-kv-cache-plan-v1",
            "backend": "simple_cpu_offload",
            "cache_id": "prefix-a",
            "load": {"mode": "require", "transport": "local_store", "cache_key": "prefix-a"},
            "store": {"mode": "skip", "transport": "none"},
            "miss_policy": "fail",
            "route_affinity": "required",
            "model_fingerprint": {},
            "operation": "load",
            "batch_key_hash": "sha256:batch",
        }
        prefix = "shared prefix " * 100
        requests = [
            InferenceRequest.from_json(
                {
                    "format": "ds4-inference-request-v1",
                    "request_id": f"cold-{idx}",
                    "capability": "efficient",
                    "chat": False,
                    "immediate": False,
                    "job_class": "analysis",
                    "max_output_tokens": 8,
                    "thinking_budget_tokens": 0,
                    "temperature": 0,
                    "input": {"prompt": f"{prefix}item {idx}"},
                    "output_contract": {"format": "text"},
                }
            )
            for idx in range(2)
        ]
        payload = {"model": "qwen27-bf16-pp8", "prompt": [request.input["prompt"] for request in requests], "extra_body": {"ds4_kv_cache": dict(plan)}, "kv_transfer_params": {"ds4_kv_cache": dict(plan)}}
        circuit = JitKvCircuitBreaker(enabled=True, min_samples=1, failure_ratio=1.0, cooldown_s=60)
        runner = OpenAICompatibleRunner(base_url="http://127.0.0.1:9", jit_kv_circuit=circuit)

        def fail_post(endpoint, body, **kwargs):
            raise RuntimeError("prefetch endpoint down")

        runner._post_json = fail_post  # type: ignore[method-assign]
        info = _maybe_prestage_common_kv_prefix(runner, payload, requests)

        self.assertIsNotNone(info)
        assert info is not None
        self.assertTrue(info["cold_dispatch"])
        self.assertEqual(info["strategy"], "jit-kv-prefetch-failed-cold-dispatch")
        self.assertNotIn("kv_transfer_params", payload)
        self.assertNotIn("extra_body", payload)
        self.assertTrue(circuit.status()["jit_kv_circuit_open"])

    def test_generated_auto_kv_prefetch_failure_keeps_kv_plan_for_cold_compute(self) -> None:
        old_prestage_auto = os.environ.get("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX")
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "0"
        try:
            plan = {
                "format": "ds4-kv-cache-plan-v1",
                "backend": "lmcache_hma",
                "cache_id": "ds4-auto:qwen27:def456",
                "load": {"mode": "prefer", "transport": "local_store", "cache_key": "ds4-auto:qwen27:def456"},
                "store": {"mode": "write_back", "transport": "local_store", "cache_key": "ds4-auto:qwen27:def456"},
                "miss_policy": "compute_and_store",
                "route_affinity": "preferred",
                "model_fingerprint": {},
                "operation": "load_store",
                "batch_key_hash": "sha256:batch",
            }
            prefix = "auto fail-open prefix " * 80
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"auto-cold-{idx}",
                        "capability": "efficient",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"{prefix}item {idx}", "shared_prefix": prefix},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            payload = {"model": "qwen27-bf16-pp13", "prompt": [request.input["prompt"] for request in requests], "extra_body": {"ds4_kv_cache": dict(plan)}, "kv_transfer_params": {"ds4_kv_cache": dict(plan)}}
            circuit = JitKvCircuitBreaker(enabled=True, min_samples=1, failure_ratio=1.0, cooldown_s=60)
            runner = OpenAICompatibleRunner(base_url="http://127.0.0.1:9", jit_kv_circuit=circuit)

            def fail_post(endpoint, body, **kwargs):
                raise RuntimeError("auto prefetch endpoint down")

            runner._post_json = fail_post  # type: ignore[method-assign]
            info = _maybe_prestage_common_kv_prefix(runner, payload, requests)

            self.assertIsNotNone(info)
            assert info is not None
            self.assertTrue(info["cold_dispatch"])
            self.assertEqual(info["strategy"], "jit-kv-prefetch-failed-auto-cold-dispatch")
            self.assertIn("kv_transfer_params", payload)
            self.assertIn("extra_body", payload)
            self.assertTrue(circuit.status()["jit_kv_circuit_open"])
        finally:
            if old_prestage_auto is None:
                os.environ.pop("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", None)
            else:
                os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = old_prestage_auto
            if old_prefetch_api is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch_api

    def test_generated_auto_kv_prefetch_timeout_fails_open_without_poisoning_circuit(self) -> None:
        old_prestage_auto = os.environ.get("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX")
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        old_timeout = os.environ.get("DS4_API_JIT_KV_PREFETCH_TIMEOUT_S")
        os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_TIMEOUT_S"] = "0.25"
        try:
            plan = {
                "format": "ds4-kv-cache-plan-v1",
                "backend": "lmcache_hma",
                "cache_id": "ds4-auto:qwen27:timeout",
                "load": {"mode": "prefer", "transport": "local_store", "cache_key": "ds4-auto:qwen27:timeout"},
                "store": {"mode": "write_back", "transport": "local_store", "cache_key": "ds4-auto:qwen27:timeout"},
                "miss_policy": "compute_and_store",
                "route_affinity": "preferred",
                "model_fingerprint": {},
                "operation": "load_store",
                "batch_key_hash": "sha256:timeout",
            }
            prefix = "auto timeout prefix " * 80
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"auto-timeout-{idx}",
                        "capability": "efficient",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"{prefix}item {idx}", "shared_prefix": prefix},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            payload = {"model": "qwen27-bf16-pp13", "prompt": [request.input["prompt"] for request in requests], "extra_body": {"ds4_kv_cache": dict(plan)}, "kv_transfer_params": {"ds4_kv_cache": dict(plan)}}
            circuit = JitKvCircuitBreaker(enabled=True, min_samples=1, failure_ratio=1.0, cooldown_s=60)
            runner = OpenAICompatibleRunner(base_url="http://127.0.0.1:9", timeout_s=3600, jit_kv_circuit=circuit)
            seen: dict[str, object] = {}

            def timeout_post(endpoint, body, **kwargs):
                seen["endpoint"] = endpoint
                seen["timeout_s"] = kwargs.get("timeout_s")
                raise TimeoutError("prefetch timed out")

            runner._post_json = timeout_post  # type: ignore[method-assign]
            info = _maybe_prestage_common_kv_prefix(runner, payload, requests)

            self.assertEqual(seen["endpoint"], "/ds4/kv/prefetch")
            self.assertEqual(seen["timeout_s"], 0.25)
            self.assertIsNotNone(info)
            assert info is not None
            self.assertTrue(info["cold_dispatch"])
            self.assertEqual(info["strategy"], "jit-kv-prefetch-unavailable-auto-cold-dispatch")
            self.assertIn("kv_transfer_params", payload)
            self.assertIn("extra_body", payload)
            status = circuit.status()
            self.assertFalse(status["jit_kv_circuit_open"])
            self.assertEqual(status["jit_kv_prefetch_failed_count"], 0)
            self.assertEqual(status["jit_kv_prefetch_submitted_count"], 1)
        finally:
            if old_prestage_auto is None:
                os.environ.pop("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", None)
            else:
                os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = old_prestage_auto
            if old_prefetch_api is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch_api
            if old_timeout is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_TIMEOUT_S", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_TIMEOUT_S"] = old_timeout

    def test_jit_kv_prefetch_timeout_response_fails_open_without_poisoning_circuit(self) -> None:
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        try:
            circuit = JitKvCircuitBreaker(enabled=True, min_samples=1, failure_ratio=1.0, cooldown_s=60)
            runner = OpenAICompatibleRunner(base_url="http://prefetch-timeout.invalid", jit_kv_circuit=circuit)
            calls: list[str] = []

            def timeout_response(endpoint, body, **kwargs):
                calls.append(endpoint)
                return {"status": "failed", "error": "timed out"}

            runner._post_json = timeout_response  # type: ignore[method-assign]

            def make_payload() -> dict[str, object]:
                plan = {"format": "ds4-kv-cache-plan-v1", "cache_id": "timeout-response"}
                return {"model": "qwen27-timeout-response", "prompt": ["prefix item"], "extra_body": {"ds4_kv_cache": dict(plan)}, "kv_transfer_params": {"ds4_kv_cache": dict(plan)}}

            prefetch_payload = {"model": "qwen27-timeout-response", "prompt": "prefix", "max_tokens": 1, "stream": False}
            payload = make_payload()
            info = run_prefetch(runner=runner, payload=payload, prefetch_payload=prefetch_payload, prefix_len=6, max_tokens=1, started=0.0, circuit=circuit, fail_open=True)

            self.assertTrue(info["cold_dispatch"])
            self.assertEqual(info["strategy"], "jit-kv-prefetch-unavailable-auto-cold-dispatch")
            self.assertNotIn("kv_transfer_params", payload)
            status = circuit.status()
            self.assertFalse(status["jit_kv_circuit_open"])
            self.assertEqual(status["jit_kv_prefetch_failed_count"], 0)
            self.assertEqual(status["jit_kv_prefetch_submitted_count"], 1)
            self.assertEqual(calls, ["/ds4/kv/prefetch"])

            second = run_prefetch(runner=runner, payload=make_payload(), prefetch_payload=prefetch_payload, prefix_len=6, max_tokens=1, started=0.0, circuit=circuit, fail_open=True)
            self.assertEqual(second["strategy"], "jit-kv-prefetch-unavailable-auto-cold-dispatch")
            self.assertEqual(calls, ["/ds4/kv/prefetch", "/ds4/kv/prefetch"])
            self.assertEqual(circuit.status()["jit_kv_prefetch_submitted_count"], 2)
            self.assertEqual(circuit.status()["jit_kv_prefetch_failed_count"], 0)
        finally:
            if old_prefetch_api is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch_api

    def test_jit_kv_prefetch_runtime_timeout_fails_open_without_poisoning_circuit(self) -> None:
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        try:
            circuit = JitKvCircuitBreaker(enabled=True, min_samples=1, failure_ratio=1.0, cooldown_s=60)
            runner = OpenAICompatibleRunner(base_url="http://prefetch-runtime-timeout.invalid", jit_kv_circuit=circuit)
            calls: list[str] = []

            def runtime_timeout(endpoint, body, **kwargs):
                calls.append(endpoint)
                raise RuntimeError("timed out")

            runner._post_json = runtime_timeout  # type: ignore[method-assign]
            plan = {"format": "ds4-kv-cache-plan-v1", "cache_id": "timeout"}
            payload = {
                "model": "qwen27-runtime-timeout",
                "prompt": ["prefix item"],
                "extra_body": {"ds4_kv_cache": dict(plan)},
                "kv_transfer_params": {"ds4_kv_cache": dict(plan)},
            }
            prefetch_payload = {"model": "qwen27-runtime-timeout", "prompt": "prefix", "max_tokens": 1, "stream": False}
            info = run_prefetch(runner=runner, payload=payload, prefetch_payload=prefetch_payload, prefix_len=6, max_tokens=1, started=0.0, circuit=circuit, fail_open=True)

            self.assertTrue(info["cold_dispatch"])
            self.assertEqual(info["strategy"], "jit-kv-prefetch-unavailable-auto-cold-dispatch")
            status = circuit.status()
            self.assertFalse(status["jit_kv_circuit_open"])
            self.assertEqual(status["jit_kv_prefetch_failed_count"], 0)
            self.assertEqual(status["jit_kv_prefetch_submitted_count"], 1)
            self.assertEqual(calls, ["/ds4/kv/prefetch"])
        finally:
            if old_prefetch_api is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch_api

    def test_generated_auto_kv_prefetch_disabled_endpoint_fails_open_without_poisoning_circuit(self) -> None:
        old_prestage_auto = os.environ.get("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX")
        old_prefetch_api = os.environ.get("DS4_API_JIT_KV_PREFETCH_API")
        os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = "1"
        os.environ["DS4_API_JIT_KV_PREFETCH_API"] = "1"
        try:
            plan = {
                "format": "ds4-kv-cache-plan-v1",
                "backend": "lmcache_hma",
                "cache_id": "ds4-auto:qwen27:disabled-endpoint",
                "load": {"mode": "prefer", "transport": "local_store", "cache_key": "ds4-auto:qwen27:disabled-endpoint"},
                "store": {"mode": "write_back", "transport": "local_store", "cache_key": "ds4-auto:qwen27:disabled-endpoint"},
                "miss_policy": "compute_and_store",
                "route_affinity": "preferred",
                "model_fingerprint": {},
                "operation": "load_store",
                "batch_key_hash": "sha256:disabled",
            }
            prefix = "auto disabled prefetch prefix " * 80
            requests = [
                InferenceRequest.from_json(
                    {
                        "format": "ds4-inference-request-v1",
                        "request_id": f"auto-disabled-{idx}",
                        "capability": "efficient",
                        "chat": False,
                        "immediate": False,
                        "job_class": "analysis",
                        "max_output_tokens": 8,
                        "thinking_budget_tokens": 0,
                        "temperature": 0,
                        "input": {"prompt": f"{prefix}item {idx}", "shared_prefix": prefix},
                        "output_contract": {"format": "text"},
                    }
                )
                for idx in range(2)
            ]
            circuit = JitKvCircuitBreaker(enabled=True, min_samples=1, failure_ratio=1.0, cooldown_s=60)
            runner = OpenAICompatibleRunner(base_url="http://disabled-prefetch.invalid", jit_kv_circuit=circuit)
            calls: list[str] = []

            def disabled_post(endpoint, body, **kwargs):
                calls.append(endpoint)
                return {"error": "DS4 KV prefetch API is disabled"}

            runner._post_json = disabled_post  # type: ignore[method-assign]

            def make_payload() -> dict[str, object]:
                return {"model": "qwen27-disabled-prefetch", "prompt": [request.input["prompt"] for request in requests], "extra_body": {"ds4_kv_cache": dict(plan)}, "kv_transfer_params": {"ds4_kv_cache": dict(plan)}}

            payload = make_payload()
            info = _maybe_prestage_common_kv_prefix(runner, payload, requests)
            self.assertIsNotNone(info)
            assert info is not None
            self.assertTrue(info["cold_dispatch"])
            self.assertEqual(info["strategy"], "jit-kv-prefetch-disabled-auto-cold-dispatch")
            self.assertIn("kv_transfer_params", payload)
            self.assertIn("extra_body", payload)
            status = circuit.status()
            self.assertFalse(status["jit_kv_circuit_open"])
            self.assertEqual(status["jit_kv_prefetch_failed_count"], 0)
            self.assertEqual(calls, ["/ds4/kv/prefetch"])

            second = _maybe_prestage_common_kv_prefix(runner, make_payload(), requests)
            self.assertIsNotNone(second)
            self.assertEqual(calls, ["/ds4/kv/prefetch"])
        finally:
            if old_prestage_auto is None:
                os.environ.pop("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", None)
            else:
                os.environ["DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX"] = old_prestage_auto
            if old_prefetch_api is None:
                os.environ.pop("DS4_API_JIT_KV_PREFETCH_API", None)
            else:
                os.environ["DS4_API_JIT_KV_PREFETCH_API"] = old_prefetch_api


if __name__ == "__main__":
    unittest.main()
