from __future__ import annotations
import json
from typing import Protocol
from ds4_tools.registry import ToolRegistry
from .tool_calls import extract_tool_calls

class ChatModel(Protocol):
    def next_message(self, messages: list[dict]) -> dict:
        ...

class FakeChatModel:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls = 0
    def next_message(self, messages: list[dict]) -> dict:
        self.calls += 1
        if not self._responses:
            return {"role": "assistant", "content": "No more fake responses."}
        return self._responses.pop(0)

def run_agent_loop(*, model: ChatModel, registry: ToolRegistry, initial_messages: list[dict] | None = None, allowed_tool_prefixes: list[str] | None = None, max_tool_rounds: int = 6, max_tool_calls: int = 20) -> dict:
    messages = list(initial_messages or [])
    allowed_tool_prefixes = allowed_tool_prefixes or ["tool:"]
    rounds: list[dict] = []
    total_tool_calls = 0
    for round_index in range(max_tool_rounds + 1):
        assistant_message = model.next_message(messages)
        messages.append(assistant_message)
        tool_calls = extract_tool_calls(assistant_message)
        if not tool_calls:
            return {"format": "ds4-agent-run-result-v1", "status": "completed", "round_count": len(rounds), "messages": messages, "rounds": rounds, "final_message": assistant_message}
        if round_index >= max_tool_rounds:
            return {"format": "ds4-agent-run-result-v1", "status": "max_tool_rounds_exceeded", "round_count": len(rounds), "messages": messages, "rounds": rounds}
        round_record = {"round_index": round_index, "tool_calls": [], "tool_results": []}
        for call in tool_calls:
            total_tool_calls += 1
            if total_tool_calls > max_tool_calls:
                return {"format": "ds4-agent-run-result-v1", "status": "max_tool_calls_exceeded", "round_count": len(rounds), "messages": messages, "rounds": rounds}
            if not any(call.tool_id.startswith(prefix) for prefix in allowed_tool_prefixes):
                result = {"format": "ds4-tool-invocation-result-v1", "tool_id": call.tool_id, "ok": False, "error": "tool_id denied by allowed_tool_prefixes"}
            else:
                result = registry.invoke(call.tool_id, call.arguments)
            round_record["tool_calls"].append({"id": call.call_id, "tool_id": call.tool_id, "source": call.source, "arguments": call.arguments})
            round_record["tool_results"].append(result)
            messages.append({"role": "tool", "tool_call_id": call.call_id, "name": call.tool_id, "content": json.dumps(_compact_tool_result(result), sort_keys=True)})
        rounds.append(round_record)
    raise AssertionError("unreachable")

def _compact_tool_result(result: dict) -> dict:
    if result.get("ok"):
        payload = result.get("result", {})
        text = json.dumps(payload, sort_keys=True)
        if len(text) > 4000:
            return {"ok": True, "summary": "tool result too large", "bytes": len(text)}
        return {"ok": True, "result": payload}
    return {"ok": False, "error": result.get("error", "tool failed"), "result": result.get("result")}
