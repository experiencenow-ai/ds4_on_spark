from __future__ import annotations
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

@dataclass(frozen=True)
class ToolAtom:
    tool_id: str
    one_line: str
    stability: str
    capability_tags: tuple[str, ...]
    executor: dict[str, Any]
    input_schema: dict[str, Any]
    policy: dict[str, Any]
    raw: dict[str, Any]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "ToolAtom":
        if data.get("format") != "ds4-tool-atom-v1":
            raise ValueError(f"unsupported tool format: {data.get('format')!r}")
        required = ["tool_id", "one_line", "stability", "capability_tags", "executor", "input_schema", "policy"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"tool record missing fields: {missing}")
        return ToolAtom(str(data["tool_id"]), str(data["one_line"]), str(data["stability"]), tuple(str(item) for item in data["capability_tags"]), dict(data["executor"]), dict(data["input_schema"]), dict(data["policy"]), dict(data))

    def brief(self) -> dict[str, Any]:
        return {"tool_id": self.tool_id, "one_line": self.one_line, "stability": self.stability, "capability_tags": list(self.capability_tags)}

class ToolRegistry:
    def __init__(self, tools: list[ToolAtom], *, root: str | Path) -> None:
        if not tools:
            raise ValueError("tool registry is empty")
        self.root = Path(root).resolve()
        self._tools = tools
        self._by_id = {tool.tool_id: tool for tool in tools}
        if len(self._by_id) != len(tools):
            raise ValueError("duplicate tool_id in registry")

    @staticmethod
    def load(path: str | Path) -> "ToolRegistry":
        registry_path = Path(path).resolve()
        tools: list[ToolAtom] = []
        with registry_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.strip()
                if stripped:
                    try:
                        tools.append(ToolAtom.from_json(json.loads(stripped)))
                    except Exception as exc:
                        raise ValueError(f"invalid tool registry line {line_number}: {exc}") from exc
        return ToolRegistry(tools, root=registry_path.parent.parent)

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        tokens = {token.lower() for token in query.replace(":", " ").replace(".", " ").split() if token}
        scored: list[tuple[int, str, ToolAtom]] = []
        for tool in self._tools:
            haystack = " ".join([tool.tool_id, tool.one_line, *tool.capability_tags]).lower()
            score = sum(1 for token in tokens if token in haystack)
            if score or not tokens:
                scored.append((-score, tool.tool_id, tool))
        return [tool.brief() for _, _, tool in sorted(scored)[:limit]]

    def describe(self, tool_id: str) -> dict[str, Any]:
        return self.get(tool_id).raw

    def get(self, tool_id: str) -> ToolAtom:
        try:
            return self._by_id[tool_id]
        except KeyError as exc:
            raise ValueError(f"unknown tool_id: {tool_id}") from exc

    def invoke(self, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started = time.time()
        try:
            tool = self.get(tool_id)
            _validate_arguments(tool.input_schema, arguments)
            result = _execute_tool(self.root, tool, arguments)
            return {"format": "ds4-tool-invocation-result-v1", "tool_id": tool_id, "ok": bool(result.get("ok", True)), "duration_s": round(time.time() - started, 6), "result": result}
        except Exception as exc:
            return {"format": "ds4-tool-invocation-result-v1", "tool_id": tool_id, "ok": False, "duration_s": round(time.time() - started, 6), "error": str(exc)}

def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if schema.get("type") != "object":
        raise ValueError("only object schemas are supported")
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    missing = [key for key in schema.get("required", []) if key not in arguments]
    if missing:
        raise ValueError(f"tool arguments missing required keys: {missing}")
    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}).keys())
        extra = sorted(set(arguments.keys()) - allowed)
        if extra:
            raise ValueError(f"tool arguments contain unsupported keys: {extra}")
    for key, value in arguments.items():
        expected = schema.get("properties", {}).get(key, {}).get("type")
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"argument {key!r} must be a string")
        if expected == "integer" and not isinstance(value, int):
            raise ValueError(f"argument {key!r} must be an integer")
        if expected == "boolean" and not isinstance(value, bool):
            raise ValueError(f"argument {key!r} must be a boolean")

def _execute_tool(root: Path, tool: ToolAtom, arguments: dict[str, Any]) -> dict[str, Any]:
    kind = str(tool.executor.get("kind", ""))
    if kind == "python":
        callable_name = str(tool.executor.get("callable", ""))
        module_name, function_name = callable_name.split(":", 1)
        function = getattr(importlib.import_module(module_name), function_name)
        result = function(arguments)
        if not isinstance(result, dict):
            raise ValueError("python tool returned non-object result")
        return result
    if kind == "bash":
        return _execute_bash(root, tool, arguments)
    raise ValueError(f"unsupported tool executor kind: {kind}")

def _execute_bash(root: Path, tool: ToolAtom, arguments: dict[str, Any]) -> dict[str, Any]:
    argv = tool.executor.get("argv")
    if not isinstance(argv, list) or not argv:
        raise ValueError("bash executor requires non-empty argv")
    resolved: list[str] = []
    for index, item in enumerate(argv):
        if not isinstance(item, str):
            raise ValueError("bash argv items must be strings")
        if index == 0:
            executable = (root / item).resolve()
            if not str(executable).startswith(str(root)):
                raise ValueError("bash executable must stay inside registry root")
            resolved.append(str(executable))
        else:
            resolved.append(item)
    completed = subprocess.run(resolved, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=root, env=_bash_env(arguments), timeout=int(tool.policy.get("timeout_s", 30)), check=False)
    max_output_bytes = int(tool.policy.get("max_output_bytes", 65536))
    if len(completed.stdout.encode()) > max_output_bytes or len(completed.stderr.encode()) > max_output_bytes:
        raise ValueError("bash tool output exceeded max_output_bytes")
    try:
        parsed_stdout = json.loads(completed.stdout) if completed.stdout.strip() else None
    except json.JSONDecodeError:
        parsed_stdout = None
    return {"ok": completed.returncode == 0, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "json": parsed_stdout}


def _bash_env(arguments: dict[str, Any]) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "DS4_TOOL_ARGUMENTS_JSON": json.dumps(arguments, sort_keys=True),
    }
