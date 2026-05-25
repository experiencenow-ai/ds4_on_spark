from __future__ import annotations

import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import unittest

from ds4_chat.cli import VllmChatModel
from ds4_chat.cli import QueueChatModel
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.runners import AntirezRunner, OpenAICompatibleRunner, SparkHttpRunner, request_messages, request_prompt
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

    def test_vllm_chat_model_keeps_full_history_shape(self) -> None:
        with _chat_server() as url:
            model = VllmChatModel(base_url=url, model="m")
            message = model.next_message([
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
            ])
        self.assertEqual(message["role"], "assistant")
        self.assertEqual(message["content"], "chat reply")

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
            stdout = json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {"total_tokens": 1}})
            stderr = ""

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Done()

        profile = ProfileRegistry.load(PROFILES).get("dsv4_vllm_mtp_smartest_v1")
        request = make_request(chat=True)
        result = SparkHttpRunner(timeout_s=30, command_runner=runner).run_one_on_node(request, profile, "spark4+spark5")
        self.assertEqual(result["output"]["text"], "ok")
        self.assertEqual(calls[0][0][5], "spark4")
        payload = json.loads(calls[0][1]["input"])
        self.assertTrue(payload["batch_first"])
        self.assertEqual(payload["batch_payload"]["model"], "deepseek-v4-flash")


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
        if self.thread is not None:
            self.thread.join(timeout=1)


class _chat_server:
    def __enter__(self) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                assert len(payload["messages"]) == 2
                body = json.dumps({"choices": [{"message": {"role": "assistant", "content": "chat reply"}}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, format: str, *args) -> None:
                return

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_port}"

    def __exit__(self, exc_type, exc, tb) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
