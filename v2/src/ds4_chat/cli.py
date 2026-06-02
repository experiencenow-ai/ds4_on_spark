from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from ds4_agent.loop import run_agent_loop
from ds4_infer.builders import chat_request
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue
from ds4_infer.runners import make_runner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.topology import SparkTopology
from ds4_tools.registry import ToolRegistry

V2_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SYSTEM = """You are the local xhigh-style Spark operator for the DS4/Centaur system.
You may help inspect and manage Sparks. Use tools when they give a more reliable answer than guessing.
The production topology is: spark0-3 and spark6 are Qwen lanes, spark0 is the only queue/API ingress; Qwen27 BF16 and DSV4 Flash are both resident as all-Spark layer-pipeline services.
For tool use, emit DeepSeek DSML tool calls when useful, for example:
<｜DSML｜tool_calls><｜DSML｜invoke name="tool:spark.status"><｜DSML｜parameter name="node">all</｜DSML｜parameter><｜DSML｜parameter name="execute">false</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>
Do not claim that you performed a Spark action unless a tool result confirms it.
"""


class QueueChatModel:
    def __init__(self, *, queue_dir: str, profiles_dir: str, topology: str, model_alias: str, runner: str, timeout_s: int, max_tokens: int, temperature: float) -> None:
        self.queue = InferenceQueue(queue_dir)
        self.registry = ProfileRegistry.load(profiles_dir)
        self.topology = SparkTopology.load(topology)
        self.model_alias = model_alias
        self.runner = make_runner(runner, timeout_s=timeout_s)
        self.max_tokens = max_tokens
        self.temperature = temperature

    def next_message(self, messages: list[dict]) -> dict:
        request = self._request(messages)
        batch_id = "chat-" + request.request_id
        self.queue.submit_requests(requests=[request], registry=self.registry, topology=self.topology, batch_id=batch_id)
        self.queue.work(registry=self.registry, runner=self.runner, batch_id=batch_id, limit=1)
        collected = self.queue.collect(request_id=request.request_id)
        result = collected.get("result", {}) if isinstance(collected, dict) else {}
        output = result.get("output", {}) if isinstance(result, dict) else {}
        text = output.get("text", "") if isinstance(output, dict) else ""
        return {"role": "assistant", "content": str(text)}

    def _request(self, messages: list[dict]) -> InferenceRequest:
        return chat_request(messages, self.registry, self.model_alias, self.max_tokens, self.temperature)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-spark-chat")
    parser.add_argument("-m", "--model-alias", default="ds4v", help="profile id or alias: ds4v, qwen, fast")
    parser.add_argument("--mode", choices=["queue"], default="queue")
    parser.add_argument("--history", default=str(Path.home() / ".ds4_spark_chat_history.json"))
    parser.add_argument("--queue-dir", default=str(Path.home() / ".ds4_v2_chat_queue"))
    parser.add_argument("--profiles-dir", default=str(V2_ROOT / "profiles" / "models"))
    parser.add_argument("--topology", default=str(V2_ROOT / "profiles" / "topology" / "static_sparks.json"))
    parser.add_argument("--runner", choices=["pipeline", "spark", "auto", "vllm", "antirez", "fake"], default="pipeline")
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
    model = QueueChatModel(queue_dir=args.queue_dir, profiles_dir=args.profiles_dir, topology=args.topology, model_alias=args.model_alias, runner=args.runner, timeout_s=args.timeout_s, max_tokens=args.max_tokens, temperature=args.temperature)
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


def _ask_once(*, model: QueueChatModel, registry: ToolRegistry | None, messages: list[dict], user_text: str, allowed_prefixes: list[str], max_tool_rounds: int) -> dict[str, Any]:
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


if __name__ == "__main__":
    sys.exit(main())
