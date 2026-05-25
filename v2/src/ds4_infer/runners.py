from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any, Protocol
from urllib import error, request as urlrequest

from .profiles import ModelProfile
from .schemas import InferenceRequest, make_result


class Runner(Protocol):
    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        ...


class NodeRunner(Protocol):
    def run_one_on_node(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None) -> dict:
        ...


class FakeRunner:
    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        contract = request.output_contract.get("format", "text")
        if contract == "centaur-atom-edit-v1":
            text = json.dumps(
                {
                    "format": "centaur-atom-edit-v1",
                    "edit_kind": "no_candidate",
                    "target_atom_id": request.input.get("target_atom_id", "unknown"),
                    "source_atom_hash": request.input.get("source_atom_hash", "unknown"),
                    "reason": "fake runner contract response",
                },
                sort_keys=True,
            )
        else:
            text = f"fake response for {request.request_id}: {str(request.input.get('suffix', ''))[:80]}"
        return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)


class CommandRunner:
    def __init__(self, command: list[str], cwd: Path | None = None, timeout_s: int = 300) -> None:
        if not command:
            raise ValueError("command runner requires argv")
        self.command = command
        self.cwd = cwd
        self.timeout_s = timeout_s

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        payload = {"request": request.raw, "profile": profile.to_public_dict()}
        completed = subprocess.run(self.command, input=json.dumps(payload), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.cwd, timeout=self.timeout_s, check=False)
        if completed.returncode != 0:
            return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": completed.stderr[-4000:]}), status="transport_failed")
        return make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=completed.stdout)


class SparkHttpRunner:
    def __init__(self, *, timeout_s: int = 300, command_runner: Any | None = None) -> None:
        self.timeout_s = timeout_s
        self.command_runner = command_runner or subprocess.run
        self.base_url = os.environ.get("DS4_SPARK_HTTP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        self.batch_first = os.environ.get("DS4_SPARK_BATCH_FIRST", "1") != "0"
        self.node_map = _json_env("DS4_SPARK_NODE_MAP_JSON")

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        return self.run_one_on_node(request, profile, None)

    def run_one_on_node(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None) -> dict:
        started = time.time()
        host = self._host(node_id)
        payload = self._payload(request, profile)
        try:
            data = self._remote_post(host, payload)
            text = extract_openai_chat_text(data) if request.chat else extract_openai_completion_text(data)
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(data))
            result["transport"] = {"node_id": host, "base_url": self.base_url, "duration_s": round(time.time() - started, 6)}
            return result
        except Exception as exc:
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": str(exc)}, sort_keys=True), status="transport_failed")
            result["transport"] = {"node_id": host, "base_url": self.base_url, "duration_s": round(time.time() - started, 6), "error": str(exc)}
            return result

    def _host(self, node_id: str | None) -> str:
        raw = (node_id or os.environ.get("DS4_SPARK_DEFAULT_NODE") or "spark4").split("+", 1)[0]
        mapped = self.node_map.get(raw, raw)
        return str(mapped)

    def _payload(self, request: InferenceRequest, profile: ModelProfile) -> dict[str, Any]:
        item: dict[str, Any] = {"custom_id": request.request_id, "max_tokens": request.max_output_tokens, "temperature": request.temperature}
        if request.chat:
            item["messages"] = request_messages(request)
        else:
            item["prompt"] = request_prompt(request)
        return {
            "request_id": request.request_id,
            "model": profile.model_id,
            "batch_first": self.batch_first,
            "batch_payload": {"model": profile.model_id, "items": [item], "concurrency": 1, "timeout_s": self.timeout_s, "max_tokens": request.max_output_tokens},
            "openai_endpoint": "/v1/chat/completions" if request.chat else "/v1/completions",
            "openai_payload": _openai_payload(request, profile),
        }

    def _remote_post(self, host: str, payload: dict[str, Any]) -> dict[str, Any]:
        remote = r'''
import json,sys,urllib.error,urllib.request
base_url = __import__("os").environ.get("DS4_SPARK_HTTP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
payload = json.loads(sys.stdin.read())
def post(endpoint, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base_url + endpoint, data=data, headers={"content-type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=%d) as response:
        return json.loads(response.read().decode("utf-8"))
try:
    result = None
    if payload.get("batch_first"):
        try:
            batch = post("/ds4/batches", payload["batch_payload"])
            result = batch.get("results", [{}])[0].get("response", batch)
        except Exception:
            result = None
    if result is None:
        result = post(payload["openai_endpoint"], payload["openai_payload"])
    print(json.dumps(result, sort_keys=True))
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")[-4000:]
    raise SystemExit("HTTP %%s: %%s" %% (exc.code, detail))
''' % self.timeout_s
        completed = self.command_runner(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, "python3 -c " + shlex.quote(remote)],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout_s + 15,
            check=False,
        )
        if int(completed.returncode) != 0:
            raise RuntimeError(str(completed.stderr)[-4000:])
        return json.loads(str(completed.stdout))


class OpenAICompatibleRunner:
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, timeout_s: int = 300, chat_endpoint: str = "/v1/chat/completions", completion_endpoint: str = "/v1/completions", default_extra_body: dict[str, Any] | None = None) -> None:
        self.base_url = (base_url or os.environ.get("DS4_OPENAI_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("DS4_OPENAI_API_KEY", "")
        self.timeout_s = timeout_s
        self.chat_endpoint = chat_endpoint
        self.completion_endpoint = completion_endpoint
        self.default_extra_body = dict(default_extra_body or {})

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        started = time.time()
        try:
            if request.chat:
                data = self._post_json(self.chat_endpoint, self._chat_payload(request, profile))
                text = extract_openai_chat_text(data)
            else:
                data = self._post_json(self.completion_endpoint, self._completion_payload(request, profile))
                text = extract_openai_completion_text(data)
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(data))
            result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6)}
            return result
        except Exception as exc:
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": str(exc)}, sort_keys=True), status="transport_failed")
            result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6), "error": str(exc)}
            return result

    def _chat_payload(self, request: InferenceRequest, profile: ModelProfile) -> dict[str, Any]:
        payload = _openai_payload(request, profile)
        _merge_extra_body(payload, self.default_extra_body)
        return payload

    def _completion_payload(self, request: InferenceRequest, profile: ModelProfile) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": profile.model_id, "prompt": request_prompt(request), "temperature": request.temperature, "max_tokens": request.max_output_tokens}
        if request.thinking_budget_tokens > 0:
            payload["extra_body"] = {"thinking_budget_tokens": request.thinking_budget_tokens}
        _merge_extra_body(payload, self.default_extra_body)
        return payload

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        req = urlrequest.Request(self.base_url + endpoint, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as response:
                text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        return json.loads(text)


class VllmOpenAIRunner(OpenAICompatibleRunner):
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, timeout_s: int = 300) -> None:
        super().__init__(base_url=base_url or os.environ.get("DS4_VLLM_BASE_URL") or os.environ.get("DS4_VLLM_MTP_BASE_URL"), api_key=api_key if api_key is not None else os.environ.get("DS4_VLLM_API_KEY", ""), timeout_s=timeout_s, default_extra_body=_json_env("DS4_VLLM_EXTRA_BODY_JSON"))


class AntirezRunner:
    def __init__(self, *, base_url: str | None = None, timeout_s: int = 300) -> None:
        self.base_url = (base_url or os.environ.get("DS4_ANTIREZ_BASE_URL") or "http://127.0.0.1:8080").rstrip("/")
        self.timeout_s = timeout_s

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        started = time.time()
        try:
            payload = {"model": profile.model_id, "prompt": request_prompt(request), "temperature": request.temperature, "max_tokens": request.max_output_tokens, "n_predict": request.max_output_tokens, "stream": False}
            data = self._post_json("/completion", payload)
            text = extract_completion_like_text(data)
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(data))
            result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6)}
            return result
        except Exception as exc:
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": str(exc)}, sort_keys=True), status="transport_failed")
            result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6), "error": str(exc)}
            return result

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(self.base_url + endpoint, data=body, headers={"content-type": "application/json"}, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as response:
                text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        return json.loads(text)


class AutoRunner:
    def __init__(self, *, timeout_s: int = 300) -> None:
        self._vllm = VllmOpenAIRunner(timeout_s=timeout_s)
        self._antirez = AntirezRunner(timeout_s=timeout_s)

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        if profile.backend in {"vllm", "vllm_mtp"}:
            return self._vllm.run_one(request, profile)
        if profile.backend == "antirez":
            return self._antirez.run_one(request, profile)
        return self._vllm.run_one(request, profile)


def request_prompt(request: InferenceRequest) -> str:
    data = request.input
    if isinstance(data.get("prompt"), str):
        return str(data["prompt"])
    parts: list[str] = []
    for key in ("shared_prefix", "suffix", "target", "instruction"):
        value = data.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if not parts and isinstance(data.get("messages"), list):
        parts.extend(str(message.get("content", "")) for message in data["messages"] if isinstance(message, dict))
    return "\n\n".join(parts)


def request_messages(request: InferenceRequest) -> list[dict[str, str]]:
    raw_messages = request.input.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        messages: list[dict[str, str]] = []
        for message in raw_messages:
            if isinstance(message, dict):
                messages.append({"role": str(message.get("role", "user")), "content": str(message.get("content", ""))})
        if messages:
            return messages
    messages = []
    system = request.input.get("system")
    if isinstance(system, str) and system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": request_prompt(request)})
    return messages


def extract_openai_chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        if isinstance(message, dict):
            for key in ("content", "reasoning_content", "reasoning"):
                if message.get(key) is not None:
                    return str(message.get(key))
            if message.get("tool_calls"):
                return json.dumps(message, sort_keys=True)
    return json.dumps(data, sort_keys=True)


def extract_openai_completion_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        text = choices[0].get("text") if isinstance(choices[0], dict) else None
        if text is not None:
            return str(text)
    return extract_completion_like_text(data)


def extract_completion_like_text(data: dict[str, Any]) -> str:
    for key in ("content", "response", "text", "completion", "generated_text"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        for key in ("text", "content"):
            value = choices[0].get(key)
            if isinstance(value, str):
                return value
    return json.dumps(data, sort_keys=True)


def make_runner(kind: str, *, timeout_s: int) -> Any:
    if kind == "fake":
        return FakeRunner()
    if kind == "auto":
        return AutoRunner(timeout_s=timeout_s)
    return SparkHttpRunner(timeout_s=timeout_s)


def _openai_payload(request: InferenceRequest, profile: ModelProfile) -> dict[str, Any]:
    if request.chat:
        payload: dict[str, Any] = {"model": profile.model_id, "messages": request_messages(request), "temperature": request.temperature, "max_tokens": request.max_output_tokens}
    else:
        payload = {"model": profile.model_id, "prompt": request_prompt(request), "temperature": request.temperature, "max_tokens": request.max_output_tokens}
    if request.thinking_budget_tokens > 0:
        payload["extra_body"] = {"thinking_budget_tokens": request.thinking_budget_tokens}
    return payload


def _usage_from_response(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage")
    return dict(usage) if isinstance(usage, dict) else {}


def _json_env(name: str) -> dict[str, Any]:
    value = os.environ.get(name)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _merge_extra_body(payload: dict[str, Any], extra_body: dict[str, Any]) -> None:
    if not extra_body:
        return
    existing = payload.get("extra_body")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(extra_body)
    payload["extra_body"] = merged
