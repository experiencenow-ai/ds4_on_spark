from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any, Protocol

from .builders import model_batch_payload, request_messages, request_prompt
from .profiles import ModelProfile
from .schemas import InferenceRequest, make_result


class Runner(Protocol):
    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        ...


class NodeRunner(Protocol):
    def run_one_on_node(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None) -> dict:
        ...


class BatchNodeRunner(Protocol):
    def run_many_on_node(self, requests: list[InferenceRequest], profile: ModelProfile, node_id: str | None, *, concurrency: int = 1) -> dict[str, dict]:
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
        self.node_map = _json_env("DS4_SPARK_NODE_MAP_JSON")

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        return self.run_one_on_node(request, profile, None)

    def run_one_on_node(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None) -> dict:
        return self.run_many_on_node([request], profile, node_id, concurrency=1)[request.request_id]

    def run_many_on_node(self, requests: list[InferenceRequest], profile: ModelProfile, node_id: str | None, *, concurrency: int = 1) -> dict[str, dict]:
        started = time.time()
        request_list = list(requests)
        if not request_list:
            return {}
        try:
            host = self._host(node_id)
            payload = self._payload_many(request_list, profile, concurrency=concurrency)
            batch = self._remote_post_batch(host, payload)
            return self._batch_results(request_list, profile, host, batch, started, concurrency)
        except Exception as exc:
            return {request.request_id: self._transport_failure(request, profile, node_id, started, str(exc)) for request in request_list}

    def _host(self, node_id: str | None) -> str:
        raw = node_id or os.environ.get("DS4_SPARK_DEFAULT_NODE")
        if not raw:
            raise ValueError("spark runner requires selected node_id or DS4_SPARK_DEFAULT_NODE")
        mapped = self.node_map.get(raw)
        if mapped is None:
            if "+" in raw:
                mapped = raw.rsplit("+", 1)[-1]
            else:
                mapped = self.node_map.get(raw, raw)
        return str(mapped)

    def _payload(self, request: InferenceRequest, profile: ModelProfile) -> dict[str, Any]:
        return self._payload_many([request], profile, concurrency=1)

    def _payload_many(self, requests: list[InferenceRequest], profile: ModelProfile, *, concurrency: int) -> dict[str, Any]:
        return {
            "request_ids": [request.request_id for request in requests],
            "model": profile.model_id,
            "batch_payload": model_batch_payload(requests, profile, timeout_s=self.timeout_s, concurrency=concurrency),
        }

    def _remote_post_batch(self, host: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    batch = post("/ds4/batches", payload["batch_payload"])
    print(json.dumps(batch, sort_keys=True))
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

    def _batch_results(self, requests: list[InferenceRequest], profile: ModelProfile, host: str, batch: dict[str, Any], started: float, concurrency: int) -> dict[str, dict]:
        rows = batch.get("results")
        if not isinstance(rows, list):
            raise RuntimeError(f"invalid DS4 batch response: {json.dumps(batch, sort_keys=True)[-4000:]}")
        by_id = {str(row.get("custom_id")): row for row in rows if isinstance(row, dict) and row.get("custom_id") is not None}
        out: dict[str, dict] = {}
        for index, request in enumerate(requests):
            row = by_id.get(request.request_id)
            if row is None and index < len(rows) and isinstance(rows[index], dict):
                row = rows[index]
            if not isinstance(row, dict):
                out[request.request_id] = self._transport_failure(request, profile, host, started, "missing DS4 batch item")
                continue
            if not row.get("ok"):
                out[request.request_id] = self._transport_failure(request, profile, host, started, json.dumps(row, sort_keys=True)[-4000:])
                continue
            response = row.get("response", batch)
            response = response if isinstance(response, dict) else {"text": str(response)}
            text = extract_openai_chat_text(response) if request.chat else extract_openai_completion_text(response)
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(response))
            result["transport"] = {"node_id": host, "base_url": self.base_url, "endpoint": "/ds4/batches", "batch_size": len(requests), "batch_concurrency": concurrency, "duration_s": round(time.time() - started, 6)}
            out[request.request_id] = result
        return out

    def _transport_failure(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None, started: float, error: str) -> dict:
        result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": error}, sort_keys=True), status="transport_failed")
        result["transport"] = {"node_id": node_id, "base_url": self.base_url, "endpoint": "/ds4/batches", "duration_s": round(time.time() - started, 6), "error": error}
        return result


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
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        if isinstance(message, dict) and message.get("content") is not None:
            return str(message.get("content"))
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
    if kind == "spark":
        return SparkHttpRunner(timeout_s=timeout_s)
    raise ValueError(f"unknown runner: {kind}")


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
