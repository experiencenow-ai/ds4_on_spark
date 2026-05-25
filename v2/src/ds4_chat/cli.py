from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib import error, request as urlrequest

from ds4_agent.loop import run_agent_loop
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue
from ds4_infer.runners import AutoRunner, FakeRunner, SparkHttpRunner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.topology import SparkTopology
from ds4_tools.registry import ToolRegistry

V2_ROOT = Path(__file__).resolve().parents[2]
MODEL_ALIASES = {
    "ds4a": "dsv4_antirez_smart_v1",
    "ds4v": "dsv4_vllm_mtp_smartest_v1",
    "qwen": "qwen3_6_27b_fp8_efficient_v1",
    "fast": "qwen3_6_35b_a3b_fp8_fastest_v1",
}

DEFAULT_SYSTEM = """You are the local xhigh-style Spark operator for the DS4/Centaur system.
You may help inspect and manage Sparks. Use tools when they give a more reliable answer than guessing.
The production topology is: spark0-3 are Qwen lanes, spark4+spark5 together are the DSV4/vLLM/MTP lane, spark6 is antirez/support, spark7 is the experiment lane.
For tool use, emit DeepSeek DSML tool calls when useful, for example:
<｜DSML｜tool_calls><｜DSML｜invoke name="tool:spark.status"><｜DSML｜parameter name="node">all</｜DSML｜parameter><｜DSML｜parameter name="execute">false</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>
Do not claim that you performed a Spark action unless a tool result confirms it.
"""


class VllmChatModel:
    def __init__(self, *, base_url: str, model: str, api_key: str = "", timeout_s: int = 300, max_tokens: int = 1024, temperature: float = 0.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.temperature = temperature

    def next_message(self, messages: list[dict]) -> dict:
        payload = {"model": self.model, "messages": _json_safe_messages(messages), "temperature": self.temperature, "max_tokens": self.max_tokens}
        body = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        req = urlrequest.Request(self.base_url + "/v1/chat/completions", data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-4000:]
            return {"role": "assistant", "content": f"[transport error HTTP {exc.code}] {detail}"}
        except Exception as exc:
            return {"role": "assistant", "content": f"[transport error] {exc}"}
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            if isinstance(message, dict):
                result: dict[str, Any] = {"role": str(message.get("role", "assistant")), "content": str(message.get("content", ""))}
                if "tool_calls" in message:
                    result["tool_calls"] = message["tool_calls"]
                return result
        return {"role": "assistant", "content": json.dumps(data, sort_keys=True)}


class QueueChatModel:
    def __init__(self, *, queue_dir: str, profiles_dir: str, topology: str, model_alias: str, runner: str, timeout_s: int, max_tokens: int, temperature: float) -> None:
        self.queue = InferenceQueue(queue_dir)
        self.registry = ProfileRegistry.load(profiles_dir)
        self.topology = SparkTopology.load(topology)
        self.model_alias = model_alias
        self.runner = _make_queue_runner(runner, timeout_s)
        self.max_tokens = max_tokens
        self.temperature = temperature

    def next_message(self, messages: list[dict]) -> dict:
        request = self._request(messages)
        batch_id = "chat-" + request.request_id
        self.queue.submit_requests(requests=[request], registry=self.registry, topology=self.topology, batch_id=batch_id)
        self.queue.work(registry=self.registry, runner=self.runner, limit=1)
        collected = self.queue.collect(request_id=request.request_id)
        result = collected.get("result", {}) if isinstance(collected, dict) else {}
        output = result.get("output", {}) if isinstance(result, dict) else {}
        text = output.get("text", "") if isinstance(output, dict) else ""
        return {"role": "assistant", "content": str(text)}

    def _request(self, messages: list[dict]) -> InferenceRequest:
        profile_id = MODEL_ALIASES.get(self.model_alias, self.model_alias)
        profile = self.registry.get(profile_id)
        safe = _json_safe_messages(messages)
        chat = bool(profile.supports_chat)
        data: dict[str, Any] = {
            "format": "ds4-inference-request-v1",
            "request_id": f"chat-{int(__import__('time').time() * 1000)}",
            "capability": None,
            "chat": chat,
            "immediate": True,
            "job_class": _chat_job_class(profile.supported_job_classes, chat),
            "max_output_tokens": self.max_tokens,
            "thinking_budget_tokens": 0,
            "temperature": self.temperature,
            "input": {"messages": safe, "prompt": _transcript(safe)},
            "output_contract": {"format": "text"},
            "model_pin": {"profile_id": profile.profile_id},
        }
        return InferenceRequest.from_json(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-spark-chat")
    parser.add_argument("-m", "--model-alias", default="ds4v", help="profile id or alias: ds4v, ds4a, qwen, fast")
    parser.add_argument("--mode", choices=["queue", "direct-vllm"], default="queue")
    parser.add_argument("--base-url", default=os.environ.get("DS4_VLLM_MTP_BASE_URL") or os.environ.get("DS4_VLLM_BASE_URL") or "http://spark4:8000")
    parser.add_argument("--model", default=os.environ.get("DS4_VLLM_MTP_MODEL") or "deepseek-v4")
    parser.add_argument("--api-key", default=os.environ.get("DS4_VLLM_API_KEY", ""))
    parser.add_argument("--history", default=str(Path.home() / ".ds4_spark_chat_history.json"))
    parser.add_argument("--queue-dir", default=str(Path.home() / ".ds4_v2_chat_queue"))
    parser.add_argument("--profiles-dir", default=str(V2_ROOT / "profiles" / "models"))
    parser.add_argument("--topology", default=str(V2_ROOT / "profiles" / "topology" / "static_sparks.json"))
    parser.add_argument("--runner", choices=["spark", "auto", "fake"], default="spark")
    parser.add_argument("--registry", default=str(V2_ROOT / "tools" / "registry.jsonl"))
    parser.add_argument("--system", default=DEFAULT_SYSTEM)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout-s", type=int, default=300)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tool-rounds", type=int, default=6)
    parser.add_argument("--allow-spark7-tools", action="store_true")
    parser.add_argument("--no-tools", action="store_true")
    parser.add_argument("--ask", help="single question mode; if omitted, enter a simple REPL")
    args = parser.parse_args(argv)

    history_path = Path(args.history)
    messages = _load_history(history_path)
    if not messages:
        messages.append({"role": "system", "content": args.system})
    if args.mode == "queue":
        model = QueueChatModel(queue_dir=args.queue_dir, profiles_dir=args.profiles_dir, topology=args.topology, model_alias=args.model_alias, runner=args.runner, timeout_s=args.timeout_s, max_tokens=args.max_tokens, temperature=args.temperature)
    else:
        model = VllmChatModel(base_url=args.base_url, model=args.model, api_key=args.api_key, timeout_s=args.timeout_s, max_tokens=args.max_tokens, temperature=args.temperature)
    registry = ToolRegistry.load(args.registry) if not args.no_tools else None
    allowed_prefixes = ["tool:ds4.", "tool:web.", "tool:spark.status", "tool:spark.transfer."]
    if args.allow_spark7_tools:
        allowed_prefixes.append("tool:spark7.")

    if args.ask is not None:
        answer = _ask_once(model=model, registry=registry, messages=messages, user_text=args.ask, allowed_prefixes=allowed_prefixes, max_tool_rounds=args.max_tool_rounds)
        _save_history(history_path, answer["messages"])
        print(answer["final_message"].get("content", ""))
        return 0

    print("DS4 Spark chat. Ctrl-D to exit. Tools enabled." if registry else "DS4 Spark chat. Ctrl-D to exit. Tools disabled.")
    if args.allow_spark7_tools:
        print("spark7 command tool is enabled for this session.")
    while True:
        try:
            user_text = input("you> ").strip()
        except EOFError:
            print()
            break
        if not user_text:
            continue
        answer = _ask_once(model=model, registry=registry, messages=messages, user_text=user_text, allowed_prefixes=allowed_prefixes, max_tool_rounds=args.max_tool_rounds)
        messages = answer["messages"]
        _save_history(history_path, messages)
        print("assistant>", answer["final_message"].get("content", ""))
    return 0


def _ask_once(*, model: VllmChatModel, registry: ToolRegistry | None, messages: list[dict], user_text: str, allowed_prefixes: list[str], max_tool_rounds: int) -> dict[str, Any]:
    run_messages = list(messages)
    run_messages.append({"role": "user", "content": user_text})
    if registry is None:
        assistant_message = model.next_message(run_messages)
        run_messages.append(assistant_message)
        return {"messages": run_messages, "final_message": assistant_message}
    result = run_agent_loop(model=model, registry=registry, initial_messages=run_messages, allowed_tool_prefixes=allowed_prefixes, max_tool_rounds=max_tool_rounds)
    final_message = result.get("final_message") or {"role": "assistant", "content": f"agent stopped: {result.get('status')}"}
    return {"messages": result.get("messages", run_messages), "final_message": final_message, "agent_result": result}


def _load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _save_history(path: Path, messages: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _json_safe_messages(messages: list[dict]) -> list[dict]:
    safe: list[dict] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        safe_message: dict[str, Any] = {"role": role, "content": str(content)}
        if "tool_call_id" in message:
            safe_message["tool_call_id"] = str(message["tool_call_id"])
        if "name" in message:
            safe_message["name"] = str(message["name"])
        if "tool_calls" in message:
            safe_message["tool_calls"] = message["tool_calls"]
        safe.append(safe_message)
    return safe


def _transcript(messages: list[dict]) -> str:
    return "\n".join(f"{message.get('role','user')}: {message.get('content','')}" for message in messages)


def _make_queue_runner(kind: str, timeout_s: int):
    if kind == "fake":
        return FakeRunner()
    if kind == "auto":
        return AutoRunner(timeout_s=timeout_s)
    return SparkHttpRunner(timeout_s=timeout_s)


def _chat_job_class(supported: tuple[str, ...], chat: bool) -> str:
    preferred = ("tool_chat", "analysis", "summary", "atom_edit") if chat else ("analysis", "atom_edit", "summary")
    for job_class in preferred:
        if job_class in supported:
            return job_class
    return supported[0]


if __name__ == "__main__":
    sys.exit(main())
