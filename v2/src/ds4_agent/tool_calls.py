from __future__ import annotations
from dataclasses import dataclass
import json
import re
from typing import Any

@dataclass(frozen=True)
class ToolCall:
    call_id: str
    tool_id: str
    arguments: dict[str, Any]
    source: str

def extract_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    calls.extend(_extract_openai_tool_calls(message))
    content = message.get("content")
    if isinstance(content, str):
        calls.extend(_extract_dsml_tool_calls(content))
    return calls

def _extract_openai_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    raw_calls = message.get("tool_calls") or []
    calls: list[ToolCall] = []
    for index, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function", {})
        name = function.get("name") if isinstance(function, dict) else None
        raw_arguments = function.get("arguments", "{}") if isinstance(function, dict) else "{}"
        if not name:
            continue
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw_arguments": raw_arguments}
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            arguments = {"_raw_arguments": raw_arguments}
        calls.append(ToolCall(str(raw_call.get("id") or f"call_{index}"), str(name), arguments, "openai"))
    return calls

_DSML_BLOCK_RE = re.compile(r"<｜DSML｜tool_calls>(.*?)</｜DSML｜tool_calls>", re.DOTALL)
_DSML_INVOKE_RE = re.compile(r"<｜DSML｜invoke\s+name=\"([^\"]+)\"\s*>(.*?)</｜DSML｜invoke>", re.DOTALL)
_DSML_PARAM_RE = re.compile(r"<｜DSML｜parameter\s+name=\"([^\"]+)\"[^>]*>(.*?)</｜DSML｜parameter>", re.DOTALL)

def _extract_dsml_tool_calls(content: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    call_index = 0
    for block in _DSML_BLOCK_RE.findall(content):
        for tool_name, body in _DSML_INVOKE_RE.findall(block):
            arguments = {name: value.strip() for name, value in _DSML_PARAM_RE.findall(body)}
            calls.append(ToolCall(f"dsml_{call_index}", tool_name, arguments, "dsml"))
            call_index += 1
    return calls
