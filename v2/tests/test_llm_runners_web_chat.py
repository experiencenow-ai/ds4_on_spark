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
from ds4_infer.runners import SparkHttpRunner, extract_openai_completion_text, request_messages, request_prompt
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


class LlmRunnersWebChatTests(unittest.TestCase):
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

        class Done:
            returncode = 0
            stdout = json.dumps({"results": [{"custom_id": "r", "ok": True, "response": {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"total_tokens": 1}}}]})
            stderr = ""

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Done()

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        request = make_request(chat=True)
        result = SparkHttpRunner(timeout_s=30, command_runner=runner).run_one_on_node(request, profile, "spark4+spark5")
        self.assertEqual(result["output"]["text"], "ok")
        self.assertEqual(calls[0][0][5], "spark5")
        payload = json.loads(calls[0][1]["input"])
        self.assertEqual(payload["batch_payload"]["model"], "deepseek-ai/DeepSeek-V4-Flash")
        self.assertEqual(payload["batch_payload"]["items"][0]["thinking"], {"type": "disabled"})
        self.assertNotIn("chat_template_kwargs", payload["batch_payload"]["items"][0])
        self.assertNotIn("openai_endpoint", payload)

    def test_spark_http_runner_batches_multiple_requests_in_one_gateway_call(self) -> None:
        calls = []

        class Done:
            returncode = 0
            stdout = json.dumps(
                {
                    "results": [
                        {"custom_id": "r", "ok": True, "response": {"choices": [{"message": {"content": "one"}}]}},
                        {"custom_id": "r2", "ok": True, "response": {"choices": [{"message": {"content": "two"}}]}},
                    ]
                }
            )
            stderr = ""

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Done()

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        first = make_request(chat=True)
        raw = make_request(chat=True).raw
        raw["request_id"] = "r2"
        results = SparkHttpRunner(timeout_s=30, command_runner=runner).run_many_on_node([first, InferenceRequest.from_json(raw)], profile, "spark4+spark5", concurrency=2)
        payload = json.loads(calls[0][1]["input"])
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

    def test_spark_http_runner_disables_qwen_thinking_with_chat_template_kwargs(self) -> None:
        calls = []

        class Done:
            returncode = 0
            stdout = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
            stderr = ""

        def runner(command, **kwargs):
            calls.append(kwargs)
            return Done()

        profile = ProfileRegistry.load(PROFILES).get("qwen3_6_27b_fp8_efficient_v1")
        raw = make_request(chat=True).raw
        raw["capability"] = "efficient"
        raw["job_class"] = "summary"
        SparkHttpRunner(timeout_s=30, command_runner=runner).run_one_on_node(InferenceRequest.from_json(raw), profile, "spark0")
        item = json.loads(calls[0]["input"])["batch_payload"]["items"][0]
        self.assertEqual(item["thinking"], {"type": "disabled"})
        self.assertEqual(item["chat_template_kwargs"], {"enable_thinking": False})

    def test_spark_http_runner_adds_thinking_budget_to_generation_cap(self) -> None:
        calls = []

        class Done:
            returncode = 0
            stdout = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
            stderr = ""

        def runner(command, **kwargs):
            calls.append(kwargs)
            return Done()

        profile = ProfileRegistry.load(PROFILES).get("qwen3_6_27b_fp8_efficient_v1")
        raw = make_request(chat=True).raw
        raw["capability"] = "efficient"
        raw["job_class"] = "summary"
        raw["max_output_tokens"] = 64
        raw["thinking_budget_tokens"] = 100
        SparkHttpRunner(timeout_s=30, command_runner=runner).run_one_on_node(InferenceRequest.from_json(raw), profile, "spark0")
        payload = json.loads(calls[0]["input"])
        item = payload["batch_payload"]["items"][0]
        self.assertEqual(item["max_tokens"], 164)
        self.assertEqual(item["thinking"], {"type": "enabled", "budget_tokens": 100})
        self.assertEqual(item["thinking_token_budget"], 100)
        self.assertEqual(item["chat_template_kwargs"], {"enable_thinking": True})

    def test_spark_http_runner_can_map_group_to_ingress_node(self) -> None:
        calls = []

        class Done:
            returncode = 0
            stdout = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})
            stderr = ""

        def runner(command, **kwargs):
            calls.append(command)
            return Done()

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        with patch.dict(os.environ, {"DS4_SPARK_NODE_MAP_JSON": json.dumps({"spark4+spark5": "spark5"})}):
            SparkHttpRunner(command_runner=runner).run_one_on_node(make_request(chat=True), profile, "spark4+spark5")
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


class _local_html_server:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")
        self.httpd: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        body = self.body

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("content-type", "text/html; charset=utf-8")
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


class _local_json_server:
    def __init__(self, response: dict) -> None:
        self.response = json.dumps(response).encode("utf-8")
        self.httpd: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        response = self.response

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
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
