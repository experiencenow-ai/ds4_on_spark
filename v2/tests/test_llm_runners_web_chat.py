from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import unittest
from unittest.mock import patch

from ds4_chat.cli import QueueChatModel
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import AntirezRunner, OpenAICompatibleRunner, SparkHttpRunner, extract_openai_completion_text, request_messages, request_prompt
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


class CapturingAntirezRunner(AntirezRunner):
    def __init__(self) -> None:
        super().__init__(base_url="http://unused")
        self.calls: list[tuple[str, dict]] = []

    def _post_json(self, endpoint: str, payload: dict) -> dict:
        self.calls.append((endpoint, payload))
        if endpoint == "/completion":
            raise RuntimeError("HTTP 404: not found")
        return {"choices": [{"text": "thinking out loud</think>ANTIREZ_OK"}], "usage": {"total_tokens": 5}}


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
        registry = ProfileRegistry.load(PROFILES)
        runner = CapturingRunner()
        chat_profile = registry.resolve(capability="smartest", chat=True, job_class="tool_chat")
        completion_profile = registry.resolve(capability="smart", chat=False, job_class="atom_edit")
        chat_result = runner.run_one(make_request(chat=True), chat_profile)
        completion_result = runner.run_one(make_request(chat=False), completion_profile)
        self.assertEqual(chat_result["output"]["text"], "chat ok")
        self.assertEqual(completion_result["output"]["text"], "completion ok")
        self.assertEqual(runner.calls[0][0], "/v1/chat/completions")
        self.assertEqual(runner.calls[1][0], "/v1/completions")

    def test_antirez_runner_falls_back_to_openai_completion_endpoint(self) -> None:
        registry = ProfileRegistry.load(PROFILES)
        runner = CapturingAntirezRunner()
        profile = registry.resolve(capability="smart", chat=False, job_class="atom_edit")
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
        self.assertEqual(calls[0]["command"][5], "spark5")
        payload = json.loads(calls[0]["input"])
        self.assertEqual(payload["batch_payload"]["model"], "deepseek-ai/DeepSeek-V4-Flash")
        self.assertEqual(payload["batch_payload"]["items"][0]["thinking"], {"type": "disabled"})
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
            ("dsv4_vllm_mtp_smartest_v1", {"max_output_tokens": 64, "thinking_budget_tokens": 100}, "spark4+spark5", {"type": "enabled", "budget_tokens": 100}, {"thinking": True}, 164),
        ]
        for profile_id, updates, node, thinking, template_kwargs, max_tokens in cases:
            item = _captured_batch_item(profile_id, updates=updates, node=node)
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
        self.assertEqual(calls[0][5], "spark5")

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

    def test_completion_extractor_accepts_chat_shaped_response(self) -> None:
        data = {"choices": [{"message": {"content": "dsv4 antirez ok", "reasoning_content": "hidden"}}]}
        self.assertEqual(extract_openai_completion_text(data), "dsv4 antirez ok")


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
