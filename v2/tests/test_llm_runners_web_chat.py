from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import unittest
from unittest.mock import patch

from ds4_chat.cli import QueueChatModel
from ds4_infer.profiles import ModelProfile, ProfileRegistry
from ds4_infer.runners import AntirezRunner, OpenAICompatibleRunner, PipelineOpenAIRunner, SparkHttpRunner, extract_openai_chat_text, extract_openai_completion_text, request_messages, request_prompt
from ds4_infer.schemas import InferenceRequest
from ds4_tools.builtin import spark7_run_command, web_fetch
from ds4_tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles" / "models"
TOOLS = ROOT / "tools" / "registry.jsonl"


def make_request(*, chat: bool) -> InferenceRequest:
    return InferenceRequest.from_json(
        {
            "format": "ds4-inference-request-v1",
            "request_id": "r",
            "capability": "smartest" if chat else "smart",
            "chat": chat,
            "immediate": True,
            "job_class": "tool_chat" if chat else "atom_edit",
            "max_output_tokens": 64,
            "thinking_budget_tokens": 0,
            "temperature": 0,
            "input": {"shared_prefix": "system rules", "suffix": "target atom"},
            "output_contract": {"format": "text"},
        }
    )


class CapturingRunner(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.calls: list[tuple[str, dict]] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        self.calls.append((endpoint, payload))
        if endpoint.endswith("/chat/completions"):
            return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}], "usage": {"total_tokens": 3}}
        return {"choices": [{"text": "completion ok"}], "usage": {"total_tokens": 2}}


class CapturingCoalescedRunner(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.calls: list[tuple[str, dict]] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        self.calls.append((endpoint, payload))
        return {
            "choices": [{"index": 0, "text": "one"}, {"index": 1, "text": "two"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 128, "total_tokens": 148},
        }


class CapturingChatBatchRunner(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.calls: list[tuple[str, dict]] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        self.calls.append((endpoint, payload))
        return {
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "chat one"}},
                {"index": 1, "message": {"role": "assistant", "content": "chat two"}},
            ],
            "usage": {"prompt_tokens": 20, "completion_tokens": 24, "total_tokens": 44},
        }


class CapturingAntirezRunner(AntirezRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.calls: list[tuple[str, dict]] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        self.calls.append((endpoint, payload))
        if endpoint == "/completion":
            raise RuntimeError("HTTP 404: not found")
        return {"choices": [{"text": "thinking out loud</think>ANTIREZ_OK"}], "usage": {"total_tokens": 5}}


class StreamingCompletionBackend(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.calls: list[tuple[str, dict]] = []

    def _post_sse_json(self, endpoint: str, payload: dict, **kwargs):
        self.calls.append((endpoint, payload))
        assert endpoint == self.completion_endpoint
        assert payload["stream"] is True
        assert len(payload["prompt"]) == 2
        yield {"choices": [{"index": 1, "text": "second", "finish_reason": None}]}
        yield {"choices": [{"index": 0, "text": "first", "finish_reason": None}]}
        yield {"choices": [{"index": 1, "text": " done", "finish_reason": "stop"}]}
        yield {"choices": [{"index": 0, "text": " done", "finish_reason": "stop"}]}

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        raise AssertionError("streaming test should not use non-streaming post")


class SlowTailStreamingBackend(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")

    def _post_sse_json(self, endpoint: str, payload: dict, **kwargs):
        yield {"choices": [{"index": 0, "text": "first done", "finish_reason": "stop"}]}
        time.sleep(0.02)
        yield {"choices": [{"index": 1, "text": "tail", "finish_reason": None}]}

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        raise AssertionError("streaming timeout test should not use non-streaming post")


class CancellableStreamingBackend(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.cancel_event_seen = False
        self.tail_requested = False

    def _post_sse_json(self, endpoint: str, payload: dict, *, cancel_event: threading.Event | None = None):
        assert endpoint == self.completion_endpoint
        assert payload["stream"] is True
        self.cancel_event_seen = cancel_event is not None
        if cancel_event is not None:
            cancel_event.set()
        yield {"choices": [{"index": 0, "text": "first done", "finish_reason": "stop"}]}
        self.tail_requested = True
        yield {"choices": [{"index": 1, "text": "tail", "finish_reason": "stop"}]}

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        raise AssertionError("streaming cancellation test should not use non-streaming post")


class StreamingChatBackend(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.payloads: list[dict] = []

    def _post_sse_json(self, endpoint: str, payload: dict, **kwargs):
        assert endpoint == self.chat_endpoint
        assert payload["stream"] is True
        self.payloads.append(payload)
        yield {"choices": [{"delta": {"content": "chat"}, "finish_reason": None}]}
        yield {"choices": [{"delta": {"content": " done"}, "finish_reason": "stop"}]}

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        raise AssertionError("parallel chat streaming test should not use non-streaming post")


class CancellableStreamingChatBackend(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.cancel_event_seen = False
        self.tail_requested = False

    def _post_sse_json(self, endpoint: str, payload: dict, *, cancel_event: threading.Event | None = None):
        assert endpoint == self.chat_endpoint
        assert payload["stream"] is True
        self.cancel_event_seen = cancel_event is not None
        if cancel_event is not None:
            cancel_event.set()
        yield {"choices": [{"delta": {"content": "partial"}, "finish_reason": None}]}
        self.tail_requested = True
        yield {"choices": [{"delta": {"content": " tail"}, "finish_reason": "stop"}]}

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        raise AssertionError("parallel chat cancellation test should not use non-streaming post")


class SlowChatBatchBackend(OpenAICompatibleRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.calls: list[dict] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        assert endpoint == self.chat_batch_endpoint
        self.calls.append(payload)
        text = json.dumps(payload)
        if "second target" in text:
            return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "second done"}}], "usage": {"completion_tokens": 2}}
        time.sleep(0.03)
        return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "first done"}}], "usage": {"completion_tokens": 2}}

    def _post_sse_json(self, endpoint: str, payload: dict, **kwargs):
        raise AssertionError("chat batch incremental test should not use SSE")


class StreamingPipelineRunner(PipelineOpenAIRunner):
    def __init__(self) -> None:
        super().__init__(base_urls={"svc": "http://unused"})
        self.backend = StreamingCompletionBackend()

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> StreamingCompletionBackend:
        return self.backend


class SlowTailStreamingPipelineRunner(PipelineOpenAIRunner):
    def __init__(self) -> None:
        super().__init__(base_urls={"svc": "http://unused"})

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> SlowTailStreamingBackend:
        return SlowTailStreamingBackend()


class CancellableStreamingPipelineRunner(PipelineOpenAIRunner):
    def __init__(self) -> None:
        super().__init__(base_urls={"svc": "http://unused"})
        self.backend = CancellableStreamingBackend()

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> CancellableStreamingBackend:
        return self.backend


class StreamingChatPipelineRunner(PipelineOpenAIRunner):
    def __init__(self) -> None:
        super().__init__(base_urls={"svc": "http://unused"})
        self.backend = StreamingChatBackend()

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> StreamingChatBackend:
        return self.backend


class CancellableStreamingChatPipelineRunner(PipelineOpenAIRunner):
    def __init__(self) -> None:
        super().__init__(base_urls={"svc": "http://unused"})
        self.backend = CancellableStreamingChatBackend()

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> CancellableStreamingChatBackend:
        return self.backend


class SlowChatBatchPipelineRunner(PipelineOpenAIRunner):
    def __init__(self) -> None:
        super().__init__(base_urls={"svc": "http://unused"})
        self.backend = SlowChatBatchBackend()

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> SlowChatBatchBackend:
        return self.backend


class NonStreamingCoalescedPipelineRunner(PipelineOpenAIRunner):
    def __init__(self) -> None:
        super().__init__(base_urls={"svc": "http://unused"})
        self.backend = CapturingCoalescedRunner()

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> CapturingCoalescedRunner:
        return self.backend


def _chat_payload(content: str = "ok") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class _JsonDone:
    returncode = 0
    stderr = ""

    def __init__(self, payload: dict) -> None:
        self.stdout = json.dumps(payload)


def _json_runner(calls: list, payload: dict, *, capture: str = "kwargs"):
    def runner(command, **kwargs):
        calls.append(command if capture == "command" else dict({"command": command}, **kwargs))
        return _JsonDone(payload)
    return runner


def _captured_batch_item(profile_id: str, *, updates: dict | None = None, node: str = "spark0") -> dict:
    calls = []
    raw = make_request(chat=True).raw
    raw.update(updates or {})
    profile = ProfileRegistry.load(PROFILES).get(profile_id)
    runner = SparkHttpRunner(timeout_s=30, command_runner=_json_runner(calls, _chat_payload()))
    runner.run_one_on_node(InferenceRequest.from_json(raw), profile, node)
    return json.loads(calls[0]["input"])["batch_payload"]["items"][0]


class LlmRunnersWebChatTests(unittest.TestCase):
    def test_openai_runner_uses_chat_and_completion_endpoints(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "plain-chat",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["tool_chat"],
                "supports_chat": True,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        runner = CapturingRunner()
        chat_result = runner.run_one(make_request(chat=True), profile)
        completion_result = runner.run_one(make_request(chat=False), profile)
        self.assertEqual(chat_result["output"]["text"], "chat ok")
        self.assertEqual(completion_result["output"]["text"], "completion ok")
        self.assertEqual(runner.calls[0][0], "/v1/chat/completions")
        self.assertEqual(runner.calls[1][0], "/v1/completions")

    def test_openai_runner_coalesces_compatible_completion_batch(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        first = make_request(chat=False)
        first.raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 64}
        first = InferenceRequest.from_json(first.raw)
        raw = make_request(chat=False).raw
        raw["request_id"] = "r2"
        raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 64}
        runner = CapturingCoalescedRunner()
        result = runner.run_many_completion([first, InferenceRequest.from_json(raw)], profile)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], "/v1/completions")
        self.assertIsInstance(runner.calls[0][1]["prompt"], list)
        self.assertEqual(len(runner.calls[0][1]["prompt"]), 2)
        self.assertEqual(result["r"]["output"]["text"], "one")
        self.assertEqual(result["r2"]["output"]["text"], "two")
        self.assertEqual(result["r"]["usage"]["completion_tokens"], 64)
        self.assertEqual(result["r2"]["transport"]["coalesced_batch_size"], 2)

    def test_openai_runner_coalesces_mixed_completion_subgroups(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        requests = []
        for request_id, tokens in (("r", 64), ("r2", 128), ("r3", 64), ("r4", 128)):
            raw = make_request(chat=False).raw
            raw["request_id"] = request_id
            raw["max_output_tokens"] = tokens
            raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": tokens}
            requests.append(InferenceRequest.from_json(raw))
        runner = CapturingCoalescedRunner()

        result = runner.run_many_completion(requests, profile)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(sorted(payload["max_tokens"] for _, payload in runner.calls), [64, 128])
        self.assertEqual([len(payload["prompt"]) for _, payload in runner.calls], [2, 2])
        self.assertTrue(all(row["transport"]["coalesced_completion_batch"] for row in result.values()))
        self.assertEqual({row["transport"]["coalesced_batch_size"] for row in result.values()}, {2})

    def test_openai_runner_does_not_coalesce_chat_batch(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        runner = CapturingCoalescedRunner()
        self.assertIsNone(runner.run_many_completion([make_request(chat=True), make_request(chat=True)], profile))
        self.assertEqual(runner.calls, [])

    def test_openai_runner_coalesces_chat_batch_with_chat_endpoint(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "batch-chat",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["tool_chat"],
                "supports_chat": True,
                "supports_completion": True,
                "supports_thinking": False,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        runner = CapturingChatBatchRunner()

        result = runner.run_many_chat([make_request(chat=True), InferenceRequest.from_json(second_raw)], profile)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], "/v1/chat/completions/batch")
        self.assertEqual(len(runner.calls[0][1]["messages"]), 2)
        self.assertEqual(runner.calls[0][1]["messages"][0][0]["role"], "user")
        self.assertEqual(result["r"]["output"]["text"], "chat one")
        self.assertEqual(result["r2"]["output"]["text"], "chat two")
        self.assertTrue(result["r"]["transport"]["coalesced_chat_batch"])

    def test_openai_runner_can_parallelize_chat_with_standard_endpoint(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "parallel-chat",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["tool_chat"],
                "supports_chat": True,
                "supports_completion": True,
                "supports_thinking": False,
                "production_eligible": True,
                "routing": {
                    "chat_cohort_transport": "parallel_chat_completions",
                    "parallel_chat_concurrency": 2,
                    "served_model_name": "served-model",
                },
            }
        )
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        runner = CapturingRunner()

        result = runner.run_many_chat([make_request(chat=True), InferenceRequest.from_json(second_raw)], profile)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual([call[0] for call in runner.calls], ["/v1/chat/completions", "/v1/chat/completions"])
        self.assertTrue(all(isinstance(call[1]["messages"], list) for call in runner.calls))
        self.assertTrue(result["r"]["transport"]["coalesced_chat_parallel"])
        self.assertEqual(result["r2"]["transport"]["coalesced_batch_size"], 2)

    def test_parallel_chat_can_salt_members_with_request_id_extra_body(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "parallel-chat-salted",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["tool_chat"],
                "supports_chat": True,
                "supports_completion": True,
                "supports_thinking": False,
                "production_eligible": True,
                "routing": {
                    "chat_cohort_transport": "parallel_chat_completions",
                    "parallel_chat_payload_salt": "extra_body_request_id",
                    "parallel_chat_concurrency": 2,
                    "served_model_name": "served-model",
                },
            }
        )
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        runner = CapturingRunner()

        result = runner.run_many_chat([make_request(chat=True), InferenceRequest.from_json(second_raw)], profile)

        self.assertIsNotNone(result)
        self.assertEqual(sorted(call[1]["extra_body"]["request_id"] for call in runner.calls), ["r", "r2"])

    def test_openai_runner_coalesces_rendered_chat_as_completion_prompts(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "completion-prompts",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["tool_chat"],
                "supports_chat": True,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {
                    "chat_cohort_transport": "completion_prompts",
                    "served_model_name": "served-model",
                },
            }
        )
        first_raw = make_request(chat=True).raw
        first_raw["input"]["rendered_prompt"] = "rendered chat one"
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        second_raw["input"]["rendered_prompt"] = "rendered chat two"
        runner = CapturingCoalescedRunner()

        result = runner.run_many_chat([InferenceRequest.from_json(first_raw), InferenceRequest.from_json(second_raw)], profile)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(runner.calls[0][0], "/v1/completions")
        self.assertEqual(runner.calls[0][1]["prompt"], ["rendered chat one", "rendered chat two"])
        self.assertEqual(result["r"]["output"]["text"], "one")
        self.assertTrue(result["r"]["transport"]["chat_as_completion_prompts"])

    def test_openai_runner_can_parallelize_rendered_chat_completion_prompts(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "rendered-completion-parallel",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["tool_chat"],
                "supports_chat": True,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {
                    "chat_cohort_transport": "parallel_completion_prompts",
                    "parallel_chat_concurrency": 2,
                    "served_model_name": "served-model",
                },
            }
        )
        first_raw = make_request(chat=True).raw
        first_raw["input"]["rendered_prompt"] = "rendered chat one"
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        second_raw["input"]["rendered_prompt"] = "rendered chat two"
        runner = CapturingRunner()

        result = runner.run_many_chat([InferenceRequest.from_json(first_raw), InferenceRequest.from_json(second_raw)], profile)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual([call[0] for call in runner.calls], ["/v1/completions", "/v1/completions"])
        self.assertEqual({call[1]["prompt"] for call in runner.calls}, {"rendered chat one", "rendered chat two"})
        self.assertTrue(result["r"]["transport"]["coalesced_chat_parallel_completion"])
        self.assertTrue(result["r2"]["transport"]["chat_as_completion_prompts"])

    def test_kimi_profiles_use_rendered_completion_prompt_transport(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        for profile_id in ("kimi26_pp13_smart_v1", "kimi27_code_pp13_smart_v1"):
            profile = registry.get(profile_id)
            self.assertEqual(profile.routing.get("chat_cohort_transport"), "parallel_completion_prompts")
            raw = make_request(chat=True).raw
            raw["input"]["rendered_prompt"] = "<|im_assistant|>assistant<|im_middle|><think></think>"
            runner = CapturingRunner()

            result = runner.run_one(InferenceRequest.from_json(raw), profile)

            self.assertEqual(runner.calls[0][0], "/v1/completions")
            self.assertEqual(runner.calls[0][1]["prompt"], "<|im_assistant|>assistant<|im_middle|><think></think>")
            self.assertTrue(result["transport"]["chat_as_completion_prompts"])

    def test_dsv4_profile_uses_native_chat_even_when_rendered_prompt_is_present(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        raw = make_request(chat=True).raw
        raw["input"]["rendered_prompt"] = "rendered single chat"
        runner = CapturingRunner()

        result = runner.run_one(InferenceRequest.from_json(raw), profile)

        self.assertEqual(runner.calls[0][0], "/v1/chat/completions")
        self.assertIsInstance(runner.calls[0][1]["messages"], list)
        self.assertEqual(result["output"]["text"], "chat ok")
        self.assertNotIn("chat_as_completion_prompts", result["transport"])

    def test_openai_runner_attaches_auto_kv_cache_ref_for_resident_pipeline(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        profile = registry.get("dsv4_vllm_mtp_pp8_smartest_v1")
        runner = CapturingRunner()

        with patch.dict(os.environ, {"DS4_PIPELINE_AUTO_KV_CACHE": "1", "DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS": "dsv4_flash_pp8"}):
            runner.run_one(make_request(chat=True), profile)

        payload = runner.calls[0][1]
        plan = payload["extra_body"]["ds4_kv_cache"]
        self.assertEqual(plan["backend"], "dsv4_hma")
        self.assertEqual(plan["load"]["mode"], "prefer")
        self.assertEqual(plan["store"]["mode"], "write_back")
        self.assertEqual(plan["miss_policy"], "compute_and_store")
        self.assertEqual(payload["kv_transfer_params"]["cache_ref"], plan["cache_id"])
        self.assertEqual(payload["kv_transfer_params"]["simple_kv_cache_ref"], plan["cache_id"])

    def test_openai_runner_does_not_override_explicit_kv_cache_plan(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "explicit-kv",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["tool_chat"],
                "supports_chat": True,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"pipeline": {"service_id": "dsv4_flash_pp8", "served_model_name": "served-model"}},
            }
        )
        raw = make_request(chat=True).raw
        raw["input"]["kv_cache_plan"] = {
            "format": "ds4-kv-cache-plan-v1",
            "backend": "dsv4_hma",
            "cache_id": "explicit",
            "load": {"mode": "prefer", "transport": "local_store", "cache_key": "explicit"},
            "store": {"mode": "skip", "transport": "none"},
            "miss_policy": "compute",
            "route_affinity": "preferred",
            "model_fingerprint": {},
            "operation": "load",
            "batch_key_hash": "sha256:explicit",
        }
        runner = CapturingRunner()

        with patch.dict(os.environ, {"DS4_PIPELINE_AUTO_KV_CACHE": "1", "DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS": "dsv4_flash_pp8"}):
            runner.run_one(InferenceRequest.from_json(raw), profile)

        self.assertEqual(runner.calls[0][1]["extra_body"]["ds4_kv_cache"]["cache_id"], "explicit")

    def test_pipeline_runner_streams_coalesced_completion_results_incrementally(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = make_request(chat=False)
        first.raw["max_output_tokens"] = 11
        first.raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 11}
        first.raw["input"]["ds4_client_stream"] = True
        first = InferenceRequest.from_json(first.raw)
        second_raw = make_request(chat=False).raw
        second_raw["request_id"] = "r2"
        second_raw["max_output_tokens"] = 11
        second_raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 11}
        second_raw["input"]["ds4_client_stream"] = True
        seen = []
        results = StreamingPipelineRunner().run_many_on_node_incremental(
            [first, InferenceRequest.from_json(second_raw)],
            profile,
            None,
            concurrency=2,
            on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
        )
        self.assertEqual(seen, [("r2", "second done"), ("r", "first done")])
        self.assertEqual(results["r"]["transport"]["coalesced_completion_streaming"], True)
        self.assertEqual(results["r"]["usage"]["completion_tokens"], 11)

    def test_pipeline_runner_uses_internal_streaming_for_nonstreaming_incremental_worker(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = make_request(chat=False)
        first = InferenceRequest.from_json(first.raw)
        second_raw = make_request(chat=False).raw
        second_raw["request_id"] = "r2"
        seen = []
        results = StreamingPipelineRunner().run_many_on_node_incremental(
            [first, InferenceRequest.from_json(second_raw)],
            profile,
            None,
            concurrency=2,
            on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
        )
        self.assertEqual(seen, [("r2", "second done"), ("r", "first done")])
        self.assertEqual(results["r"]["transport"]["coalesced_completion_streaming"], True)
        self.assertEqual(results["r2"]["transport"]["coalesced_batch_size"], 2)

    def test_pipeline_runner_batches_mixed_completion_subgroups_incrementally(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        requests = []
        for request_id, tokens in (("r", 64), ("r2", 128), ("r3", 64), ("r4", 128)):
            raw = make_request(chat=False).raw
            raw["request_id"] = request_id
            raw["max_output_tokens"] = tokens
            raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": tokens}
            requests.append(InferenceRequest.from_json(raw))
        seen = []
        runner = NonStreamingCoalescedPipelineRunner()

        results = runner.run_many_on_node_incremental(
            requests,
            profile,
            None,
            concurrency=4,
            on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
        )

        self.assertEqual(sorted(payload["max_tokens"] for _, payload in runner.backend.calls), [64, 128])
        self.assertEqual(sorted(len(payload["prompt"]) for _, payload in runner.backend.calls), [2, 2])
        self.assertEqual(set(results), {"r", "r2", "r3", "r4"})
        self.assertEqual({row["transport"]["coalesced_batch_size"] for row in results.values()}, {2})
        self.assertTrue(all(row["transport"]["coalesced_completion_batch"] for row in results.values()))
        self.assertEqual(len(seen), 4)

    def test_pipeline_runner_publishes_chat_batch_chunks_incrementally(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": True,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = InferenceRequest.from_json(make_request(chat=True).raw)
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        second_raw["input"]["suffix"] = "second target"
        seen = []
        old = os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_MAX")
        os.environ["DS4_PIPELINE_COMPLETION_COHORT_MAX"] = "1"
        try:
            results = SlowChatBatchPipelineRunner().run_many_on_node_incremental(
                [first, InferenceRequest.from_json(second_raw)],
                profile,
                None,
                concurrency=2,
                on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
            )
        finally:
            if old is None:
                os.environ.pop("DS4_PIPELINE_COMPLETION_COHORT_MAX", None)
            else:
                os.environ["DS4_PIPELINE_COMPLETION_COHORT_MAX"] = old
        self.assertEqual(seen, [("r2", "second done"), ("r", "first done")])
        self.assertEqual(results["r"]["transport"]["coalesced_chat_batch"], True)
        self.assertEqual(results["r2"]["transport"]["coalesced_chat_planned_split"], True)
        self.assertEqual(results["r2"]["transport"]["coalesced_chat_chunk_count"], 2)

    def test_pipeline_runner_streams_parallel_chat_incremental_members(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": True,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {
                    "chat_cohort_transport": "parallel_chat_completions",
                    "parallel_chat_concurrency": 2,
                    "served_model_name": "served-model",
                },
            }
        )
        first = InferenceRequest.from_json(make_request(chat=True).raw)
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        seen = []
        results = StreamingChatPipelineRunner().run_many_on_node_incremental(
            [first, InferenceRequest.from_json(second_raw)],
            profile,
            None,
            concurrency=2,
            on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
            cancel_event=threading.Event(),
        )
        self.assertEqual(sorted(seen), [("r", "chat done"), ("r2", "chat done")])
        self.assertTrue(results["r"]["transport"]["coalesced_chat_parallel_streaming"])

    def test_pipeline_runner_parallel_chat_cancel_closes_internal_stream(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm_pipeline",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": True,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {
                    "chat_cohort_transport": "parallel_chat_completions",
                    "parallel_chat_concurrency": 1,
                    "served_model_name": "served-model",
                },
            }
        )
        first = InferenceRequest.from_json(make_request(chat=True).raw)
        second_raw = make_request(chat=True).raw
        second_raw["request_id"] = "r2"
        runner = CancellableStreamingChatPipelineRunner()
        results = runner.run_many_on_node_incremental(
            [first, InferenceRequest.from_json(second_raw)],
            profile,
            None,
            concurrency=2,
            on_result=lambda _request_id, _result: None,
            cancel_event=threading.Event(),
        )
        self.assertTrue(runner.backend.cancel_event_seen)
        self.assertFalse(runner.backend.tail_requested)
        self.assertEqual(results["r"]["status"], "transport_failed")
        self.assertIn("cancelled", results["r"]["transport"]["error"])

    def test_pipeline_runner_streaming_wall_timeout_fails_only_unfinished_tail(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = InferenceRequest.from_json(make_request(chat=False).raw)
        second_raw = make_request(chat=False).raw
        second_raw["request_id"] = "r2"
        seen = []
        old = os.environ.get("DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S")
        os.environ["DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S"] = "0.001"
        try:
            results = SlowTailStreamingPipelineRunner().run_many_on_node_incremental(
                [first, InferenceRequest.from_json(second_raw)],
                profile,
                None,
                concurrency=2,
                on_result=lambda request_id, result: seen.append((request_id, result["status"])),
            )
        finally:
            if old is None:
                os.environ.pop("DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S", None)
            else:
                os.environ["DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S"] = old
        self.assertEqual(seen, [("r", "completed"), ("r2", "transport_failed")])
        self.assertEqual(results["r"]["output"]["text"], "first done")
        self.assertIn("wall timeout", results["r2"]["transport"]["error"])

    def test_pipeline_runner_streaming_cancel_fails_only_unfinished_tail(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = InferenceRequest.from_json(make_request(chat=False).raw)
        second_raw = make_request(chat=False).raw
        second_raw["request_id"] = "r2"
        seen = []
        runner = CancellableStreamingPipelineRunner()
        results = runner.run_many_on_node_incremental(
            [first, InferenceRequest.from_json(second_raw)],
            profile,
            None,
            concurrency=2,
            on_result=lambda request_id, result: seen.append((request_id, result["status"])),
            cancel_event=threading.Event(),
        )
        self.assertTrue(runner.backend.cancel_event_seen)
        self.assertFalse(runner.backend.tail_requested)
        self.assertEqual(seen, [("r", "completed"), ("r2", "transport_failed")])
        self.assertEqual(results["r"]["output"]["text"], "first done")
        self.assertIn("cancelled", results["r2"]["transport"]["error"])

    def test_sse_reader_treats_python_timed_out_object_as_poll_timeout(self) -> None:
        class FakeResponse:
            def __init__(self) -> None:
                self.lines = [
                    OSError("cannot read from timed out object"),
                    b'data: {"choices":[{"text":"ok","finish_reason":"stop"}]}\n',
                    b"\n",
                    b"data: [DONE]\n",
                    b"\n",
                ]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def readline(self):
                item = self.lines.pop(0)
                if isinstance(item, BaseException):
                    raise item
                return item

        runner = OpenAICompatibleRunner(base_url="http://unused")
        with patch("ds4_infer.runners.urlrequest.urlopen", return_value=FakeResponse()):
            events = list(runner._post_sse_json("/v1/completions", {"model": "served"}, cancel_event=threading.Event()))
        self.assertEqual(events, [{"choices": [{"text": "ok", "finish_reason": "stop"}]}])

    def test_sse_reader_can_leave_cancel_socket_timeout_disabled(self) -> None:
        class FakeSock:
            def __init__(self) -> None:
                self.calls: list[float] = []

            def settimeout(self, value: float) -> None:
                self.calls.append(value)

        class FakeResponse:
            def __init__(self, sock: FakeSock) -> None:
                self._sock = sock
                self.lines = [b"data: [DONE]\n", b"\n"]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def readline(self):
                return self.lines.pop(0)

        old = os.environ.get("DS4_PIPELINE_SSE_CANCEL_POLL_TIMEOUT_S")
        sock = FakeSock()
        runner = OpenAICompatibleRunner(base_url="http://unused")
        try:
            os.environ["DS4_PIPELINE_SSE_CANCEL_POLL_TIMEOUT_S"] = "0"
            with patch("ds4_infer.runners.urlrequest.urlopen", return_value=FakeResponse(sock)):
                self.assertEqual(list(runner._post_sse_json("/v1/completions", {"model": "served"}, cancel_event=threading.Event())), [])
        finally:
            if old is None:
                os.environ.pop("DS4_PIPELINE_SSE_CANCEL_POLL_TIMEOUT_S", None)
            else:
                os.environ["DS4_PIPELINE_SSE_CANCEL_POLL_TIMEOUT_S"] = old
        self.assertEqual(sock.calls, [])

    def test_pipeline_runner_uses_final_only_for_forced_output_nonstreaming_worker(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = make_request(chat=False)
        first.raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 64}
        first = InferenceRequest.from_json(first.raw)
        second_raw = make_request(chat=False).raw
        second_raw["request_id"] = "r2"
        second_raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 64}
        seen = []
        runner = NonStreamingCoalescedPipelineRunner()
        results = runner.run_many_on_node_incremental(
            [first, InferenceRequest.from_json(second_raw)],
            profile,
            None,
            concurrency=2,
            on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
        )
        self.assertEqual(seen, [("r", "one"), ("r2", "two")])
        self.assertEqual(len(runner.backend.calls), 1)
        self.assertNotIn("coalesced_completion_streaming", results["r"]["transport"])
        self.assertTrue(results["r2"]["transport"]["coalesced_completion_batch"])

    def test_pipeline_runner_streams_forced_output_when_worker_can_cancel(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = make_request(chat=False)
        first.raw["max_output_tokens"] = 11
        first.raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 11}
        first = InferenceRequest.from_json(first.raw)
        second_raw = make_request(chat=False).raw
        second_raw["request_id"] = "r2"
        second_raw["max_output_tokens"] = 11
        second_raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 11}
        seen = []
        runner = StreamingPipelineRunner()
        results = runner.run_many_on_node_incremental(
            [first, InferenceRequest.from_json(second_raw)],
            profile,
            None,
            concurrency=2,
            on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
            cancel_event=threading.Event(),
        )
        self.assertEqual(seen, [("r2", "second done"), ("r", "first done")])
        self.assertEqual(len(runner.backend.calls), 1)
        self.assertEqual(results["r"]["transport"]["coalesced_completion_streaming"], True)
        self.assertEqual(results["r"]["usage"]["completion_tokens"], 11)

    def test_pipeline_runner_can_disable_internal_streaming_for_nonstreaming_worker(self) -> None:
        profile = ModelProfile.from_json(
            {
                "profile_id": "svc",
                "model_id": "served-model",
                "backend": "vllm",
                "capability_classes": ["smart"],
                "supported_job_classes": ["analysis"],
                "supports_chat": False,
                "supports_completion": True,
                "production_eligible": True,
                "routing": {"served_model_name": "served-model"},
            }
        )
        first = make_request(chat=False)
        first.raw["max_output_tokens"] = 11
        first.raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 11}
        first = InferenceRequest.from_json(first.raw)
        second_raw = make_request(chat=False).raw
        second_raw["request_id"] = "r2"
        second_raw["max_output_tokens"] = 11
        second_raw["input"]["openai"] = {"ignore_eos": True, "min_tokens": 11}
        seen = []
        old = os.environ.get("DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS")
        os.environ["DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS"] = "0"
        try:
            runner = NonStreamingCoalescedPipelineRunner()
            results = runner.run_many_on_node_incremental(
                [first, InferenceRequest.from_json(second_raw)],
                profile,
                None,
                concurrency=2,
                on_result=lambda request_id, result: seen.append((request_id, result["output"]["text"])),
            )
        finally:
            if old is None:
                os.environ.pop("DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS", None)
            else:
                os.environ["DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS"] = old
        self.assertEqual(seen, [("r", "one"), ("r2", "two")])
        self.assertEqual(len(runner.backend.calls), 1)
        self.assertNotIn("coalesced_completion_streaming", results["r"]["transport"])
        self.assertTrue(results["r2"]["transport"]["coalesced_completion_batch"])

    def test_antirez_runner_falls_back_to_openai_completion_endpoint(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        runner = CapturingAntirezRunner()
        profile = registry.get("dsv4_antirez_smart_v1")
        result = runner.run_one(make_request(chat=False), profile)
        self.assertEqual(result["output"]["text"], "ANTIREZ_OK")
        self.assertEqual([call[0] for call in runner.calls], ["/completion", "/v1/completions"])

    def test_prompt_and_message_builders_use_shared_prefix_and_suffix(self) -> None:
        request = make_request(chat=False)
        self.assertIn("system rules", request_prompt(request))
        self.assertIn("target atom", request_prompt(request))
        messages = request_messages(request)
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("target atom", messages[-1]["content"])

    def test_spark7_command_defaults_to_plan_only(self) -> None:
        result = spark7_run_command({"command": "echo ok"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["execute"])
        self.assertEqual(result["planned"]["node"], "spark7")

    def test_tool_registry_contains_web_and_spark7_tools(self) -> None:
        registry = ToolRegistry.load(TOOLS)
        self.assertIn("tool:web.fetch", [item["tool_id"] for item in registry.search("web playwright")])
        self.assertEqual(registry.describe("tool:spark7.command.run")["policy"]["side_effects"], "spark7_write")

    def test_web_fetch_text_mode_reads_local_html(self) -> None:
        with _local_html_server("<html><title>T</title><body><h1>Hello JS fallback</h1></body></html>") as url:
            result = web_fetch({"url": url, "mode": "text", "max_text_chars": 200})
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "text")
        self.assertIn("Hello JS fallback", result["text"])

    def test_queue_chat_model_can_use_fake_runner_with_model_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model = QueueChatModel(
                queue_dir=str(Path(temp_dir) / "queue"),
                profiles_dir=str(PROFILES),
                topology=str(ROOT / "profiles" / "topology" / "static_sparks.json"),
                model_alias="qwen",
                runner="fake",
                timeout_s=30,
                max_tokens=16,
                temperature=0.0,
            )
            message = model.next_message([{"role": "user", "content": "hello"}])
        self.assertEqual(message["role"], "assistant")
        self.assertIn("fake response", message["content"])

    def test_spark_http_runner_uses_selected_node_over_ssh(self) -> None:
        calls = []
        payload = {"results": [{"custom_id": "r", "ok": True, "response": dict(_chat_payload("ok"), usage={"total_tokens": 1})}]}

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        request = make_request(chat=True)
        result = SparkHttpRunner(timeout_s=30, command_runner=_json_runner(calls, payload)).run_one_on_node(request, profile, "spark4+spark5")
        self.assertEqual(result["output"]["text"], "ok")
        self.assertEqual(calls[0]["command"][-2], "spark5")
        self.assertIn("ControlMaster=auto", calls[0]["command"])
        payload = json.loads(calls[0]["input"])
        self.assertEqual(payload["batch_payload"]["model"], "deepseek-ai/DeepSeek-V4-Flash")
        self.assertNotIn("thinking", payload["batch_payload"]["items"][0])
        self.assertEqual(payload["batch_payload"]["items"][0]["chat_template_kwargs"], {"thinking": False})
        self.assertNotIn("openai_endpoint", payload)

    def test_spark_http_runner_batches_multiple_requests_in_one_gateway_call(self) -> None:
        calls = []
        payload = {"results": [{"custom_id": "r", "ok": True, "response": _chat_payload("one")}, {"custom_id": "r2", "ok": True, "response": _chat_payload("two")}]}

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        first = make_request(chat=True)
        raw = make_request(chat=True).raw
        raw["request_id"] = "r2"
        results = SparkHttpRunner(timeout_s=30, command_runner=_json_runner(calls, payload)).run_many_on_node([first, InferenceRequest.from_json(raw)], profile, "spark4+spark5", concurrency=2)
        payload = json.loads(calls[0]["input"])
        self.assertEqual(len(payload["batch_payload"]["items"]), 2)
        self.assertEqual(payload["batch_payload"]["concurrency"], 2)
        self.assertEqual(results["r"]["output"]["text"], "one")
        self.assertEqual(results["r2"]["output"]["text"], "two")

    def test_spark_http_runner_fails_closed_without_selected_node(self) -> None:
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            raise AssertionError("runner should not be called without a node")

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        result = SparkHttpRunner(timeout_s=30, command_runner=runner).run_one(make_request(chat=True), profile)
        self.assertEqual(result["status"], "transport_failed")
        self.assertIn("requires selected node_id", result["transport"]["error"])
        self.assertEqual(calls, [])

    def test_spark_http_runner_sets_profile_thinking_template_key(self) -> None:
        cases = [
            ("qwen3_6_27b_fp8_efficient_v1", {"capability": "efficient", "job_class": "summary"}, "spark0", {"type": "disabled"}, {"enable_thinking": False}, None),
            ("qwen3_6_27b_fp8_efficient_v1", {"capability": "efficient", "job_class": "summary", "max_output_tokens": 64, "thinking_budget_tokens": 100}, "spark0", {"type": "enabled", "budget_tokens": 100}, {"enable_thinking": True}, 164),
            ("gemma4_12b_it_pp8_peer_v1", {"capability": "smart", "job_class": "analysis"}, "spark0", {"type": "disabled"}, {"enable_thinking": False}, None),
            ("dsv4_vllm_mtp_smartest_v1", {}, "spark4+spark5", None, {"thinking": False}, None),
            ("dsv4_vllm_mtp_smartest_v1", {"max_output_tokens": 64, "thinking_budget_tokens": 100}, "spark4+spark5", {"type": "enabled", "budget_tokens": 100}, {"thinking": True}, 164),
        ]
        for profile_id, updates, node, thinking, template_kwargs, max_tokens in cases:
            item = _captured_batch_item(profile_id, updates=updates, node=node)
            if thinking is None:
                self.assertNotIn("thinking", item)
            else:
                self.assertEqual(item["thinking"], thinking)
            self.assertEqual(item["chat_template_kwargs"], template_kwargs)
            if max_tokens is not None:
                self.assertEqual(item["max_tokens"], max_tokens)
                self.assertEqual(item["thinking_token_budget"], 100)

    def test_spark_http_runner_can_map_group_to_ingress_node(self) -> None:
        calls = []

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        with patch.dict(os.environ, {"DS4_SPARK_NODE_MAP_JSON": json.dumps({"spark4+spark5": "spark5"})}):
            SparkHttpRunner(command_runner=_json_runner(calls, _chat_payload(), capture="command")).run_one_on_node(make_request(chat=True), profile, "spark4+spark5")
        self.assertEqual(calls[0][-2], "spark5")

    def test_spark_http_runner_rejects_failed_ds4_batch_item(self) -> None:
        with _local_json_server({"results": [{"ok": False, "status": 500, "response": {"error": "backend down"}}]}) as url:
            def runner(command, **kwargs):
                argv = shlex.split(command[-1])
                env = os.environ.copy()
                env["DS4_SPARK_HTTP_BASE_URL"] = url
                return subprocess.run(argv, input=kwargs["input"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=10, check=False)

            profile = ProfileRegistry.load(PROFILES).get("qwen3_6_27b_fp8_efficient_v1")
            result = SparkHttpRunner(timeout_s=5, command_runner=runner).run_one_on_node(make_request(chat=True), profile, "spark0")
        self.assertEqual(result["status"], "transport_failed")
        self.assertIn("backend down", result["transport"]["error"])

    def test_spark_http_runner_reports_empty_ssh_failure(self) -> None:
        def runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 255, stdout="", stderr="")

        profile = ProfileRegistry.load(PROFILES).get("qwen3_6_27b_fp8_efficient_v1")
        result = SparkHttpRunner(timeout_s=5, command_runner=runner).run_one_on_node(make_request(chat=True), profile, "spark0")
        self.assertEqual(result["status"], "transport_failed")
        self.assertIn("ssh to spark0 exited 255", result["transport"]["error"])

    def test_spark_http_runner_can_preconnect_control_master(self) -> None:
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if "-O" in command:
                return subprocess.CompletedProcess(command, 255, stdout="", stderr="No ControlPath")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        result = SparkHttpRunner(timeout_s=5, command_runner=runner).preconnect(["spark0"])
        self.assertEqual(result["results"]["spark0"]["state"], "started")
        self.assertEqual(calls[0][-1], "spark0")
        self.assertIn("ControlMaster=no", calls[0])
        self.assertIn("-M", calls[1])
        self.assertIn("ControlMaster=yes", calls[1])
        self.assertEqual(calls[1][-1], "spark0")

    def test_completion_extractor_accepts_chat_shaped_response(self) -> None:
        data = {"choices": [{"message": {"content": "dsv4 antirez ok", "reasoning_content": "hidden"}}]}
        self.assertEqual(extract_openai_completion_text(data), "dsv4 antirez ok")

    def test_chat_extractor_strips_visible_thinking(self) -> None:
        data = {"choices": [{"message": {"content": "scratch</think>final answer"}}]}
        self.assertEqual(extract_openai_chat_text(data), "final answer")


def _local_html_server(body: str):
    return _local_server("GET", body.encode("utf-8"), "text/html; charset=utf-8")


def _local_json_server(response: dict):
    return _local_server("POST", json.dumps(response).encode("utf-8"), "application/json")


class _local_server:
    def __init__(self, method: str, body: bytes, content_type: str) -> None:
        self.method = method
        self.body = body
        self.content_type = content_type
        self.httpd: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        method = self.method
        body = self.body
        content_type = self.content_type

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._send_body() if method == "GET" else self.send_error(405)

            def do_POST(self) -> None:
                self._send_body() if method == "POST" else self.send_error(405)

            def _send_body(self) -> None:
                self.send_response(200)
                self.send_header("content-type", content_type)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args) -> None:
                return

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_port}/"

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self.httpd is not None
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
