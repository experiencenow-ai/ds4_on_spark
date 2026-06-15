from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ds4_agent.loop import run_agent_loop
from ds4_infer.builders import chat_request
from ds4_infer.profiles import ProfileRegistry
from ds4_infer.queue import InferenceQueue
from ds4_infer.runners import make_runner
from ds4_infer.schemas import InferenceRequest
from ds4_infer.topology import SparkTopology
from ds4_tools.registry import ToolRegistry

V2_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DSAPI_BASE_URL = os.environ.get("DS4_API_BASE_URL", "http://spark0:8700")
REMOTE_MODEL_ALIASES = {
    "gemma": "gemma4_26b_a4b_pp13",
    "gemma4": "gemma4_26b_a4b_pp13",
    "gemma4_26b": "gemma4_26b_a4b_pp13",
    "kimi": "kimi27_pp13",
    "kimi27": "kimi27_pp13",
    "smart": "kimi27_pp13",
    "qwen": "qwen27_bf16_pp13",
    "qwen27": "qwen27_bf16_pp13",
    "fast": "qwen27_bf16_pp13",
}
DEFAULT_SYSTEM = """You are the local xhigh-style Spark operator for the DS4/Centaur system.
You may help inspect and manage Sparks. Use tools when they give a more reliable answer than guessing.
The production topology is: spark0-3 and spark6 are Qwen lanes, spark4+spark5 together are the DSV4/vLLM/MTP lane, and spark7 is the experiment lane.
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


class DsapiChatModel:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout_s: int,
        max_tokens: int,
        temperature: float,
        priority: int | None,
        stream: bool,
        stream_to_stdout: bool,
        ds4_job_class: str,
        thinking_budget_tokens: int | None,
        extra_body: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.priority = priority
        self.stream = stream
        self.stream_to_stdout = stream_to_stdout
        self.ds4_job_class = ds4_job_class
        self.thinking_budget_tokens = thinking_budget_tokens
        self.extra_body = extra_body
        self.metadata = metadata

    def next_message(self, messages: list[dict]) -> dict[str, Any]:
        payload = _dsapi_chat_payload(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            timeout_s=self.timeout_s,
            priority=self.priority,
            stream=self.stream,
            ds4_job_class=self.ds4_job_class,
            thinking_budget_tokens=self.thinking_budget_tokens,
            extra_body=self.extra_body,
            metadata=self.metadata,
        )
        started = time.time()
        if self.stream:
            text, usage, status = _post_chat_stream(self.base_url, payload, timeout_s=self.timeout_s, stream_to_stdout=self.stream_to_stdout)
            message = {"role": "assistant", "content": text}
            message["_ds4"] = {"usage": usage, "status": status, "elapsed_s": round(time.time() - started, 3), "streamed": True}
            return message
        response = _post_json(_url(self.base_url, "/v1/chat/completions"), payload, timeout_s=self.timeout_s)
        text = _chat_text_from_response(response)
        message = {"role": "assistant", "content": text}
        message["_ds4"] = {"usage": response.get("usage") or {}, "status": (response.get("ds4") or {}).get("status"), "elapsed_s": round(time.time() - started, 3), "streamed": False}
        return message

    def list_models(self) -> dict[str, Any]:
        return _get_json(_url(self.base_url, "/v1/models"), timeout_s=min(self.timeout_s, 30))

    def status(self) -> dict[str, Any]:
        return _get_json(_url(self.base_url, "/ds4/dispatcher/status"), timeout_s=min(self.timeout_s, 30))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ds4-spark-chat")
    parser.add_argument("-m", "--model-alias", default="ds4v", help="profile id or alias: ds4v, qwen, fast")
    parser.add_argument("--mode", choices=["queue", "dsapi"], default="queue")
    parser.add_argument("--model", help="DSAPI model/profile/service id. Friendly aliases: kimi, qwen, gemma.")
    parser.add_argument("--base-url", default=DEFAULT_DSAPI_BASE_URL, help=f"DSAPI base URL. Default: {DEFAULT_DSAPI_BASE_URL}")
    parser.add_argument("--history", default=str(Path.home() / ".ds4_spark_chat_history.json"))
    parser.add_argument("--queue-dir", default=str(Path.home() / ".ds4_v2_chat_queue"))
    parser.add_argument("--profiles-dir", default=str(V2_ROOT / "profiles" / "models"))
    parser.add_argument("--topology", default=str(V2_ROOT / "profiles" / "topology" / "static_sparks.json"))
    parser.add_argument("--runner", choices=["spark", "auto", "vllm", "antirez", "fake"], default="spark")
    parser.add_argument("--registry", default=str(V2_ROOT / "tools" / "registry.jsonl"))
    parser.add_argument("--system", default=DEFAULT_SYSTEM)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout-s", type=int, default=300)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--priority", type=int, help="DSAPI queue priority. Lower numbers run earlier.")
    parser.add_argument("--ds4-job-class", default="interactive")
    parser.add_argument("--thinking-budget-tokens", type=int)
    parser.add_argument("--extra-body-json", default="{}", help="JSON object merged into OpenAI extra_body.")
    parser.add_argument("--metadata-json", default="{}", help="JSON object sent as DSAPI metadata.")
    parser.add_argument("--stream", dest="stream", action="store_true", default=True)
    parser.add_argument("--no-stream", dest="stream", action="store_false")
    parser.add_argument("--show-usage", action="store_true", help="Print elapsed time and token usage after each DSAPI turn.")
    parser.add_argument("--max-tool-rounds", type=int, default=6)
    parser.add_argument("--allow-spark7-tools", action="store_true")
    parser.add_argument("--no-tools", action="store_true")
    parser.add_argument("--ask", help="single question mode; if omitted, enter a simple REPL")
    args = parser.parse_args(argv)

    history_path = Path(args.history)
    messages = _load_history(history_path)
    if not messages:
        messages.append({"role": "system", "content": args.system})
    model = _make_chat_model(args)
    registry = ToolRegistry.load(args.registry) if args.mode == "queue" and not args.no_tools else None
    allowed_prefixes = ["tool:ds4.", "tool:web.", "tool:spark.status", "tool:spark.transfer."]
    if args.allow_spark7_tools:
        allowed_prefixes.append("tool:spark7.")

    if args.ask is not None:
        answer = _ask_once(model=model, registry=registry, messages=messages, user_text=args.ask, allowed_prefixes=allowed_prefixes, max_tool_rounds=args.max_tool_rounds)
        _save_history(history_path, answer["messages"])
        _print_final(answer["final_message"], streamed=args.mode == "dsapi" and args.stream)
        if args.mode == "dsapi" and args.show_usage:
            _print_usage(answer["final_message"])
        return 0

    print(_banner(args, registry))
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
        try:
            if args.mode == "dsapi" and _handle_dsapi_command(model, user_text, messages):
                continue
        except EOFError:
            print()
            break
        if args.mode == "dsapi" and args.stream:
            print("assistant> ", end="", flush=True)
        answer = _ask_once(model=model, registry=registry, messages=messages, user_text=user_text, allowed_prefixes=allowed_prefixes, max_tool_rounds=args.max_tool_rounds)
        messages = answer["messages"]
        _save_history(history_path, messages)
        _print_final(answer["final_message"], streamed=args.mode == "dsapi" and args.stream, prefix="assistant> ")
        if args.mode == "dsapi" and args.show_usage:
            _print_usage(answer["final_message"])
    return 0


def _make_chat_model(args: argparse.Namespace) -> QueueChatModel | DsapiChatModel:
    if args.mode == "queue":
        return QueueChatModel(queue_dir=args.queue_dir, profiles_dir=args.profiles_dir, topology=args.topology, model_alias=args.model_alias, runner=args.runner, timeout_s=args.timeout_s, max_tokens=args.max_tokens, temperature=args.temperature)
    return DsapiChatModel(
        base_url=args.base_url,
        model=_remote_model(args.model, args.model_alias),
        timeout_s=args.timeout_s,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        priority=args.priority,
        stream=args.stream,
        stream_to_stdout=args.stream,
        ds4_job_class=args.ds4_job_class,
        thinking_budget_tokens=args.thinking_budget_tokens,
        extra_body=_json_object_arg(args.extra_body_json, "--extra-body-json"),
        metadata=_json_object_arg(args.metadata_json, "--metadata-json"),
    )


def _ask_once(*, model: QueueChatModel | DsapiChatModel, registry: ToolRegistry | None, messages: list[dict], user_text: str, allowed_prefixes: list[str], max_tool_rounds: int) -> dict[str, Any]:
    run_messages = list(messages)
    run_messages.append({"role": "user", "content": user_text})
    if registry is None:
        assistant_message = model.next_message(run_messages)
        run_messages.append(assistant_message)
        return {"messages": run_messages, "final_message": assistant_message}
    result = run_agent_loop(model=model, registry=registry, initial_messages=run_messages, allowed_tool_prefixes=allowed_prefixes, max_tool_rounds=max_tool_rounds)
    final_message = result.get("final_message") or {"role": "assistant", "content": f"agent stopped: {result.get('status')}"}
    return {"messages": result.get("messages", run_messages), "final_message": final_message, "agent_result": result}


def _remote_model(model: str | None, model_alias: str) -> str:
    value = model or ("kimi" if model_alias == "ds4v" else model_alias)
    return REMOTE_MODEL_ALIASES.get(value, value)


def _dsapi_chat_payload(
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    timeout_s: int,
    priority: int | None,
    stream: bool,
    ds4_job_class: str,
    thinking_budget_tokens: int | None,
    extra_body: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": _public_messages(messages),
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "stream": bool(stream),
        "ds4_timeout_s": int(timeout_s),
        "ds4_job_class": ds4_job_class,
    }
    if priority is not None:
        payload["priority"] = int(priority)
    if thinking_budget_tokens is not None:
        payload["thinking_budget_tokens"] = int(thinking_budget_tokens)
    if extra_body:
        payload["extra_body"] = extra_body
    if metadata:
        payload["metadata"] = metadata
    return payload


def _public_messages(messages: list[dict]) -> list[dict[str, Any]]:
    public = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role is None or content is None:
            continue
        public.append({"role": role, "content": content})
    return public


def _post_chat_stream(base_url: str, payload: dict[str, Any], *, timeout_s: int, stream_to_stdout: bool) -> tuple[str, dict[str, Any], str | None]:
    text_parts: list[str] = []
    usage: dict[str, Any] = {}
    status: str | None = None
    for event in _post_sse_json(_url(base_url, "/v1/chat/completions"), payload, timeout_s=timeout_s):
        choice = ((event.get("choices") or [{}])[0] or {}) if isinstance(event, dict) else {}
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        text = str(delta.get("content") or "")
        if text:
            text_parts.append(text)
            if stream_to_stdout:
                print(text, end="", flush=True)
        usage = event.get("usage") or usage
        ds4 = event.get("ds4") if isinstance(event.get("ds4"), dict) else {}
        status = str(ds4.get("status") or status or "")
    if stream_to_stdout:
        print()
    return "".join(text_parts), usage, status


def _post_sse_json(url: str, payload: dict[str, Any], *, timeout_s: int):
    request = Request(url, data=_json_bytes(payload), headers={"content-type": "application/json", "accept": "text/event-stream"}, method="POST")
    try:
        with urlopen(request, timeout=max(1, timeout_s + 10)) as response:
            for event in _iter_sse_json(response):
                yield event
    except HTTPError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    except URLError as exc:
        raise RuntimeError(f"DSAPI connection failed: {exc}") from exc


def _iter_sse_json(lines):
    data_lines: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        line = line.rstrip("\r\n")
        if not line:
            if data_lines:
                payload = "\n".join(data_lines)
                data_lines.clear()
                if payload == "[DONE]":
                    return
                yield json.loads(payload)
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if data_lines:
        payload = "\n".join(data_lines)
        if payload != "[DONE]":
            yield json.loads(payload)


def _post_json(url: str, payload: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    request = Request(url, data=_json_bytes(payload), headers={"content-type": "application/json", "accept": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=max(1, timeout_s + 10)) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    except URLError as exc:
        raise RuntimeError(f"DSAPI connection failed: {exc}") from exc


def _get_json(url: str, *, timeout_s: int) -> dict[str, Any]:
    request = Request(url, headers={"accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=max(1, timeout_s)) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(_http_error_message(exc)) from exc
    except URLError as exc:
        raise RuntimeError(f"DSAPI connection failed: {exc}") from exc


def _chat_text_from_response(response: dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "")


def _handle_dsapi_command(model: QueueChatModel | DsapiChatModel, user_text: str, messages: list[dict]) -> bool:
    if not user_text.startswith("/"):
        return False
    command, _, rest = user_text.partition(" ")
    command = command.strip().lower()
    rest = rest.strip()
    if command in {"/exit", "/quit"}:
        raise EOFError
    if command == "/help":
        print("commands: /model [alias-or-id], /models, /status, /reset, /history, /exit")
        return True
    if command == "/reset":
        system = messages[0] if messages and messages[0].get("role") == "system" else None
        messages.clear()
        if system is not None:
            messages.append(system)
        print("history reset")
        return True
    if command == "/history":
        print(f"{max(0, len(messages) - 1)} conversation message(s)")
        return True
    if not isinstance(model, DsapiChatModel):
        print(f"{command} is only available in --mode dsapi")
        return True
    if command == "/model":
        if rest:
            model.model = REMOTE_MODEL_ALIASES.get(rest, rest)
        print(f"model: {model.model}")
        return True
    if command == "/models":
        _print_json(model.list_models())
        return True
    if command == "/status":
        _print_json(model.status())
        return True
    print(f"unknown command: {command}. Try /help")
    return True


def _print_final(message: dict[str, Any], *, streamed: bool, prefix: str = "") -> None:
    if streamed:
        return
    print(f"{prefix}{message.get('content', '')}")


def _print_usage(message: dict[str, Any]) -> None:
    meta = message.get("_ds4") if isinstance(message.get("_ds4"), dict) else {}
    usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    elapsed = float(meta.get("elapsed_s") or 0.0)
    completion = int(usage.get("completion_tokens") or 0)
    rate = (completion / elapsed) if elapsed > 0 and completion > 0 else 0.0
    print(f"[ds4] status={meta.get('status')} elapsed={elapsed:.3f}s prompt_tokens={usage.get('prompt_tokens', 0)} completion_tokens={completion} completion_tok_s={rate:.2f}")


def _banner(args: argparse.Namespace, registry: ToolRegistry | None) -> str:
    if args.mode == "dsapi":
        model = _remote_model(args.model, args.model_alias)
        return f"DSAPI chat at {args.base_url} model={model}. Commands: /model, /models, /status, /reset, /exit."
    return "DS4 Spark chat. Ctrl-D to exit. Tools enabled." if registry else "DS4 Spark chat. Ctrl-D to exit. Tools disabled."


def _json_object_arg(value: str, flag: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag} must be a JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{flag} must be a JSON object")
    return parsed


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _http_error_message(exc: HTTPError) -> str:
    body = exc.read().decode("utf-8", "replace")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = body
    return f"DSAPI HTTP {exc.code}: {parsed}"


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


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
