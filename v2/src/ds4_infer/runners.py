from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterator, Protocol
from urllib import error, request as urlrequest

from .builders import model_batch_payload, request_messages, request_prompt
from .kv_cache import kv_cache_extra_body
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
        self.ssh_control_dir = Path(os.environ.get("DS4_SPARK_SSH_CONTROL_DIR", "/tmp/ds4_spark_ssh_control"))
        self.ssh_control_persist_s = int(os.environ.get("DS4_SPARK_SSH_CONTROL_PERSIST_S", "1800") or "1800")
        self.ssh_connect_timeout_s = int(os.environ.get("DS4_SPARK_SSH_CONNECT_TIMEOUT_S", "8") or "8")

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

    def preconnect(self, nodes: list[str]) -> dict[str, Any]:
        results = {}
        for node in nodes:
            host = self._host(node)
            results[node] = self.ensure_persistent_connection(host)
        return {"format": "ds4-spark-ssh-preconnect-v1", "results": results}

    def ensure_persistent_connection(self, host: str) -> dict[str, Any]:
        self.ssh_control_dir.mkdir(parents=True, exist_ok=True)
        try:
            check = self.command_runner(self._ssh_argv(host, control_master="no", control_command="check"), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.ssh_connect_timeout_s + 5, check=False)
        except subprocess.TimeoutExpired:
            check = None
        if check is not None and int(check.returncode) == 0:
            return {"host": host, "state": "connected"}
        try:
            started = self.command_runner(self._ssh_master_argv(host), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.ssh_connect_timeout_s + 5, check=False)
        except subprocess.TimeoutExpired:
            return {"host": host, "state": "failed", "error": f"ssh to {host} timed out starting persistent connection"}
        if int(started.returncode) != 0:
            return {"host": host, "state": "failed", "error": _completed_error(started, host)}
        return {"host": host, "state": "started"}

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
        self.ssh_control_dir.mkdir(parents=True, exist_ok=True)
        argv = self._ssh_argv(host, remote_command="python3 -c " + shlex.quote(remote))
        try:
            completed = self.command_runner(
                argv,
                input=json.dumps(payload),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_s + 15,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"ssh to {host} timed out after {self.timeout_s + 15}s while posting /ds4/batches") from exc
        if int(completed.returncode) != 0:
            raise RuntimeError(_completed_error(completed, host))
        return json.loads(str(completed.stdout))

    def _ssh_argv(self, host: str, *, control_master: str = "auto", control_command: str | None = None, remote_command: str | None = None) -> list[str]:
        argv = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={max(1, self.ssh_connect_timeout_s)}",
            "-o",
            f"ControlMaster={control_master}",
            "-o",
            f"ControlPath={self.ssh_control_dir / '%C'}",
            "-o",
            f"ControlPersist={max(1, self.ssh_control_persist_s)}",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
        ]
        if control_command:
            argv.extend(["-O", control_command])
        argv.append(host)
        if remote_command is not None:
            argv.append(remote_command)
        return argv

    def _ssh_master_argv(self, host: str) -> list[str]:
        return [
            "ssh",
            "-M",
            "-N",
            "-f",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={max(1, self.ssh_connect_timeout_s)}",
            "-o",
            "ControlMaster=yes",
            "-o",
            f"ControlPath={self.ssh_control_dir / '%C'}",
            "-o",
            f"ControlPersist={max(1, self.ssh_control_persist_s)}",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            host,
        ]

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


class OpenAICompatibleRunner:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: int = 300,
        chat_endpoint: str = "/v1/chat/completions",
        completion_endpoint: str = "/v1/completions",
        default_extra_body: dict[str, Any] | None = None,
    ) -> None:
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
                payload = _openai_payload(request, profile)
                _merge_extra_body(payload, self.default_extra_body)
                data = self._post_json(self.chat_endpoint, payload)
                text = extract_openai_chat_text(data)
            else:
                payload = _openai_payload(request, profile)
                _merge_extra_body(payload, self.default_extra_body)
                data = self._post_json(self.completion_endpoint, payload)
                text = extract_openai_completion_text(data)
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

    def _post_sse_json(self, endpoint: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json", "accept": "text/event-stream"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        req = urlrequest.Request(self.base_url + endpoint, data=body, headers=headers, method="POST")
        try:
            response = urlrequest.urlopen(req, timeout=self.timeout_s)
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        with response:
            event_data: list[str] = []
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    if not event_data:
                        continue
                    text = "\n".join(event_data).strip()
                    event_data = []
                    if text == "[DONE]":
                        break
                    if text:
                        yield json.loads(text)
                    continue
                if line.startswith("data:"):
                    event_data.append(line[5:].strip())
            if event_data:
                text = "\n".join(event_data).strip()
                if text and text != "[DONE]":
                    yield json.loads(text)


class PipelineOpenAIRunner:
    def __init__(
        self,
        *,
        base_urls: dict[str, str] | None = None,
        api_key: str | None = None,
        timeout_s: int = 300,
        default_base_url: str | None = None,
    ) -> None:
        env_urls = _json_env("DS4_PIPELINE_BASE_URLS_JSON")
        merged = {str(key): str(value).rstrip("/") for key, value in env_urls.items()}
        for key, value in dict(base_urls or {}).items():
            merged[str(key)] = str(value).rstrip("/")
        self.base_urls = merged
        self.default_base_url = (default_base_url or os.environ.get("DS4_PIPELINE_DEFAULT_BASE_URL") or "").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("DS4_PIPELINE_API_KEY", "")
        self.timeout_s = timeout_s
        self.default_extra_body = _json_env("DS4_PIPELINE_EXTRA_BODY_JSON")

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        return self.run_one_on_node(request, profile, None)

    def run_one_on_node(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None) -> dict:
        return self._runner_for(profile, node_id).run_one(request, profile)

    def run_many_on_node(self, requests: list[InferenceRequest], profile: ModelProfile, node_id: str | None, *, concurrency: int = 1) -> dict[str, dict]:
        request_list = list(requests)
        if not request_list:
            return {}
        coalesced = self._run_coalesced_completion_batch(request_list, profile, node_id)
        if coalesced is not None:
            return coalesced
        worker_count = max(1, min(int(concurrency), len(request_list)))
        runner = self._runner_for(profile, node_id)
        out: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(runner.run_one, item, profile): item for item in request_list}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    out[item.request_id] = future.result()
                except Exception as exc:
                    result = make_result(request=item, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": str(exc)}, sort_keys=True), status="transport_failed")
                    result["transport"] = {"node_id": node_id, "base_url": self._base_url(profile, node_id), "error": str(exc)}
                    out[item.request_id] = result
        return out

    def run_many_on_node_incremental(
        self,
        requests: list[InferenceRequest],
        profile: ModelProfile,
        node_id: str | None,
        *,
        concurrency: int = 1,
        on_result: Callable[[str, dict[str, Any]], None],
    ) -> dict[str, dict]:
        request_list = list(requests)
        if not request_list:
            return {}
        coalesced = self._run_coalesced_completion_batch_incremental(request_list, profile, node_id, on_result=on_result)
        if coalesced is not None:
            return coalesced
        worker_count = max(1, min(int(concurrency), len(request_list)))
        runner = self._runner_for(profile, node_id)
        out: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {pool.submit(runner.run_one, item, profile): item for item in request_list}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = make_result(request=item, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": str(exc)}, sort_keys=True), status="transport_failed")
                    result["transport"] = {"node_id": node_id, "base_url": self._base_url(profile, node_id), "error": str(exc)}
                out[item.request_id] = result
                on_result(item.request_id, result)
        return out

    def _run_coalesced_completion_batch(self, requests: list[InferenceRequest], profile: ModelProfile, node_id: str | None) -> dict[str, dict] | None:
        if not _env_bool("DS4_PIPELINE_COHORT_COMPLETIONS", True):
            return None
        if not _compatible_completion_cohort(requests):
            return None
        min_size = _env_int("DS4_PIPELINE_COMPLETION_COHORT_MIN", 2)
        max_size = _env_int("DS4_PIPELINE_COMPLETION_COHORT_MAX", 512)
        if len(requests) < max(1, min_size) or len(requests) > max(1, max_size):
            return None
        started = time.time()
        runner = self._runner_for(profile, node_id)
        payload = _openai_payload(requests[0], profile)
        payload["prompt"] = [request_prompt(item) for item in requests]
        _merge_extra_body(payload, self.default_extra_body)
        prefetch_info: dict[str, Any] | None = None
        try:
            prefetch_info = self._maybe_prestage_common_kv_prefix(
                runner, payload, requests
            )
            data = runner._post_json(runner.completion_endpoint, payload)
        except Exception as exc:
            return {item.request_id: self._transport_failure(item, profile, node_id, started, str(exc), coalesced=True) for item in requests}
        return self._coalesced_completion_results(
            requests, profile, node_id, data, started, prefetch_info=prefetch_info
        )

    def _run_coalesced_completion_batch_incremental(
        self,
        requests: list[InferenceRequest],
        profile: ModelProfile,
        node_id: str | None,
        *,
        on_result: Callable[[str, dict[str, Any]], None],
    ) -> dict[str, dict] | None:
        if not _env_bool("DS4_PIPELINE_COHORT_COMPLETIONS", True):
            return None
        if not _env_bool("DS4_PIPELINE_COHORT_COMPLETION_STREAMING", True):
            return None
        if not _compatible_completion_cohort(requests):
            return None
        min_size = _env_int("DS4_PIPELINE_COMPLETION_COHORT_MIN", 2)
        max_size = _env_int("DS4_PIPELINE_COMPLETION_COHORT_MAX", 512)
        if len(requests) < max(1, min_size) or len(requests) > max(1, max_size):
            return None
        started = time.time()
        runner = self._runner_for(profile, node_id)
        payload = _openai_payload(requests[0], profile)
        payload["prompt"] = [request_prompt(item) for item in requests]
        payload["stream"] = True
        _merge_extra_body(payload, self.default_extra_body)
        prefetch_info: dict[str, Any] | None = None
        out: dict[str, dict] = {}
        text_by_index = {idx: "" for idx in range(len(requests))}
        completed_indexes: set[int] = set()
        try:
            prefetch_info = self._maybe_prestage_common_kv_prefix(runner, payload, requests)
            for event in runner._post_sse_json(runner.completion_endpoint, payload):
                choices = event.get("choices")
                if not isinstance(choices, list):
                    continue
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    try:
                        index = int(choice.get("index", 0))
                    except (TypeError, ValueError):
                        index = 0
                    if index < 0 or index >= len(requests) or index in completed_indexes:
                        continue
                    text_by_index[index] += _completion_stream_choice_text(choice)
                    if choice.get("finish_reason") is None:
                        continue
                    result = self._coalesced_stream_result(requests[index], profile, node_id, text_by_index[index], started, len(requests), prefetch_info=_copy_optional_dict(prefetch_info))
                    out[requests[index].request_id] = result
                    completed_indexes.add(index)
                    on_result(requests[index].request_id, result)
        except Exception as exc:
            for index, item in enumerate(requests):
                if index in completed_indexes:
                    continue
                result = self._transport_failure(item, profile, node_id, started, str(exc), coalesced=True)
                out[item.request_id] = result
                completed_indexes.add(index)
                on_result(item.request_id, result)
            return out
        for index, item in enumerate(requests):
            if index in completed_indexes:
                continue
            text = text_by_index.get(index) or ""
            status = "completed" if text else "transport_failed"
            if status == "completed":
                result = self._coalesced_stream_result(item, profile, node_id, text, started, len(requests), prefetch_info=_copy_optional_dict(prefetch_info))
            else:
                result = self._transport_failure(item, profile, node_id, started, "stream ended before this coalesced completion finished", coalesced=True)
            out[item.request_id] = result
            completed_indexes.add(index)
            on_result(item.request_id, result)
        return out

    def _maybe_prestage_common_kv_prefix(self, runner: OpenAICompatibleRunner, payload: dict[str, Any], requests: list[InferenceRequest]) -> dict[str, Any] | None:
        if not _env_bool("DS4_PIPELINE_PRESTAGE_COMMON_KV_PREFIX", True):
            return None
        if not _payload_has_strict_kv_load(payload):
            return None
        prefix = _common_prompt_prefix(requests)
        min_chars = _env_int("DS4_PIPELINE_PRESTAGE_COMMON_PREFIX_MIN_CHARS", 1024)
        if prefix is None or len(prefix) < max(1, min_chars):
            return None
        max_tokens = max(1, _env_int("DS4_PIPELINE_PRESTAGE_MAX_TOKENS", 1))
        prefetch_payload: dict[str, Any] = {
            "model": payload["model"],
            "prompt": prefix,
            "max_tokens": max_tokens,
            "temperature": payload.get("temperature", 0),
            "stream": False,
        }
        extra_body = payload.get("extra_body")
        if isinstance(extra_body, dict):
            prefetch_payload["extra_body"] = dict(extra_body)
        started = time.time()
        runner._post_json(runner.completion_endpoint, prefetch_payload)
        return {
            "common_prefix_chars": len(prefix),
            "duration_s": round(time.time() - started, 6),
            "max_tokens": max_tokens,
            "strategy": "single-prefix-load-before-cohort",
        }

    def _coalesced_completion_results(self, requests: list[InferenceRequest], profile: ModelProfile, node_id: str | None, data: dict[str, Any], started: float, *, prefetch_info: dict[str, Any] | None = None) -> dict[str, dict]:
        choices = data.get("choices")
        if not isinstance(choices, list):
            return {item.request_id: self._transport_failure(item, profile, node_id, started, f"coalesced /v1/completions response omitted choices: {json.dumps(data, sort_keys=True)[-4000:]}", coalesced=True) for item in requests}
        by_index: dict[int, dict[str, Any]] = {}
        for offset, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            try:
                index = int(choice.get("index", offset))
            except (TypeError, ValueError):
                index = offset
            by_index[index] = choice
        out: dict[str, dict] = {}
        for index, item in enumerate(requests):
            choice = by_index.get(index)
            if choice is None:
                out[item.request_id] = self._transport_failure(item, profile, node_id, started, f"coalesced /v1/completions response omitted choice index {index}", coalesced=True)
                continue
            text = _completion_choice_text(choice)
            result = make_result(request=item, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_for_coalesced_choice(data, choice, index, len(requests)))
            result["transport"] = {
                "node_id": node_id,
                "base_url": self._base_url(profile, node_id),
                "endpoint": "/v1/completions",
                "coalesced_completion_batch": True,
                "batch_size": len(requests),
                "duration_s": round(time.time() - started, 6),
            }
            if prefetch_info is not None:
                result["transport"]["kv_prestage"] = dict(prefetch_info)
            out[item.request_id] = result
        return out

    def _coalesced_stream_result(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None, text: str, started: float, batch_size: int, *, prefetch_info: dict[str, Any] | None = None) -> dict[str, Any]:
        result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
        result["usage"].update({"completion_tokens": _estimate_text_tokens(text), "completion_tokens_estimated": True})
        result["transport"] = {
            "node_id": node_id,
            "base_url": self._base_url(profile, node_id),
            "endpoint": "/v1/completions",
            "coalesced_completion_batch": True,
            "coalesced_completion_streaming": True,
            "batch_size": batch_size,
            "duration_s": round(time.time() - started, 6),
        }
        if prefetch_info is not None:
            result["transport"]["kv_prestage"] = dict(prefetch_info)
        return result

    def _transport_failure(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None, started: float, error: str, *, coalesced: bool = False) -> dict:
        result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": error}, sort_keys=True), status="transport_failed")
        result["transport"] = {"node_id": node_id, "base_url": self._base_url(profile, node_id), "endpoint": "/v1/completions", "duration_s": round(time.time() - started, 6), "error": error}
        if coalesced:
            result["transport"]["coalesced_completion_batch"] = True
        return result

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> OpenAICompatibleRunner:
        return OpenAICompatibleRunner(
            base_url=self._base_url(profile, node_id),
            api_key=self.api_key,
            timeout_s=self.timeout_s,
            default_extra_body=self.default_extra_body,
        )

    def _base_url(self, profile: ModelProfile, node_id: str | None) -> str:
        keys = [profile.profile_id, profile.model_id]
        service_id = profile.routing.get("pipeline_service_id")
        if service_id:
            keys.insert(0, str(service_id))
        if node_id:
            keys.append(str(node_id))
        for key in keys:
            value = self.base_urls.get(key)
            if value:
                return value.rstrip("/")
        if self.default_base_url:
            return self.default_base_url
        raise ValueError(f"no pipeline base URL configured for profile {profile.profile_id!r}")


class VllmOpenAIRunner(OpenAICompatibleRunner):
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, timeout_s: int = 300) -> None:
        super().__init__(
            base_url=base_url or os.environ.get("DS4_VLLM_BASE_URL") or os.environ.get("DS4_VLLM_MTP_BASE_URL"),
            api_key=api_key if api_key is not None else os.environ.get("DS4_VLLM_API_KEY", ""),
            timeout_s=timeout_s,
            default_extra_body=_json_env("DS4_VLLM_EXTRA_BODY_JSON"),
        )


class HmaPersistentRunner(OpenAICompatibleRunner):
    def __init__(self, *, base_url: str | None = None, api_key: str | None = None, timeout_s: int = 300) -> None:
        super().__init__(
            base_url=base_url or os.environ.get("DS4_HMA_BASE_URL") or "http://spark4:8300",
            api_key=api_key if api_key is not None else os.environ.get("DS4_HMA_API_KEY", ""),
            timeout_s=timeout_s,
            default_extra_body=_json_env("DS4_HMA_EXTRA_BODY_JSON"),
        )


class AntirezRunner:
    def __init__(self, *, base_url: str | None = None, timeout_s: int = 300) -> None:
        self.base_url = (base_url or os.environ.get("DS4_ANTIREZ_BASE_URL") or "http://127.0.0.1:8080").rstrip("/")
        self.timeout_s = timeout_s
        self.completion_endpoint = os.environ.get("DS4_ANTIREZ_COMPLETION_ENDPOINT", "/completion")
        self.fallback_completion_endpoint = os.environ.get("DS4_ANTIREZ_FALLBACK_COMPLETION_ENDPOINT", "/v1/completions")

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        started = time.time()
        try:
            payload = {
                "model": profile.model_id,
                "prompt": request_prompt(request),
                "temperature": request.temperature,
                "max_tokens": request.max_output_tokens,
                "n_predict": request.max_output_tokens,
                "stream": False,
            }
            data = self._post_completion(payload)
            text = extract_completion_like_text(data)
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(data))
            result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6)}
            return result
        except Exception as exc:
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": str(exc)}, sort_keys=True), status="transport_failed")
            result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6), "error": str(exc)}
            return result

    def _post_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoints = [self.completion_endpoint]
        if self.fallback_completion_endpoint not in endpoints:
            endpoints.append(self.fallback_completion_endpoint)
        last_exc: Exception | None = None
        for endpoint in endpoints:
            try:
                return self._post_json(endpoint, payload)
            except Exception as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

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
        self._hma = HmaPersistentRunner(timeout_s=timeout_s)
        self._antirez = AntirezRunner(timeout_s=timeout_s)

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        if profile.backend == "vllm_hma":
            return self._hma.run_one(request, profile)
        if profile.backend in {"vllm", "vllm_mtp"}:
            return self._vllm.run_one(request, profile)
        if profile.backend == "antirez":
            return self._antirez.run_one(request, profile)
        return self._vllm.run_one(request, profile)


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
            return strip_visible_thinking(str(text))
    return extract_completion_like_text(data)


def _completion_choice_text(choice: dict[str, Any]) -> str:
    message = choice.get("message")
    if isinstance(message, dict) and message.get("content") is not None:
        return str(message.get("content"))
    text = choice.get("text")
    if text is not None:
        return strip_visible_thinking(str(text))
    return strip_visible_thinking(json.dumps(choice, sort_keys=True))


def _completion_stream_choice_text(choice: dict[str, Any]) -> str:
    text = choice.get("text")
    if isinstance(text, str):
        return strip_visible_thinking(text)
    delta = choice.get("delta")
    if isinstance(delta, dict):
        value = delta.get("content") or delta.get("text")
        if isinstance(value, str):
            return strip_visible_thinking(value)
    return ""


def extract_completion_like_text(data: dict[str, Any]) -> str:
    for key in ("content", "response", "text", "completion", "generated_text"):
        value = data.get(key)
        if isinstance(value, str):
            return strip_visible_thinking(value)
    choices = data.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        for key in ("text", "content"):
            value = choices[0].get(key)
            if isinstance(value, str):
                return strip_visible_thinking(value)
    return json.dumps(data, sort_keys=True)


def strip_visible_thinking(text: str) -> str:
    marker = "</think>"
    if marker not in text:
        return text
    return text.split(marker, 1)[1].lstrip()


def make_runner(kind: str, *, timeout_s: int, pipeline_base_urls: dict[str, str] | None = None) -> Any:
    if kind == "fake":
        return FakeRunner()
    if kind == "auto":
        return AutoRunner(timeout_s=timeout_s)
    if kind == "vllm":
        return VllmOpenAIRunner(timeout_s=timeout_s)
    if kind == "pipeline":
        return PipelineOpenAIRunner(timeout_s=timeout_s, base_urls=pipeline_base_urls)
    if kind == "hma":
        return HmaPersistentRunner(timeout_s=timeout_s)
    if kind == "antirez":
        return AntirezRunner(timeout_s=timeout_s)
    if kind == "spark":
        return SparkHttpRunner(timeout_s=timeout_s)
    raise ValueError(f"unknown runner: {kind}")


def _openai_payload(request: InferenceRequest, profile: ModelProfile) -> dict[str, Any]:
    model = _served_model_id(profile)
    if request.chat:
        payload: dict[str, Any] = {
            "model": model,
            "messages": request_messages(request),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
    else:
        payload = {
            "model": model,
            "prompt": request_prompt(request),
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
    sampling = openai_sampling_controls(request.input)
    if sampling:
        payload.update(sampling)
    if request.thinking_budget_tokens > 0:
        payload["extra_body"] = {"thinking_budget_tokens": request.thinking_budget_tokens}
    extra_body = kv_cache_extra_body(request.input)
    if extra_body:
        payload["extra_body"] = {**dict(payload.get("extra_body") or {}), **extra_body}
    return payload


def openai_sampling_controls(input_payload: dict[str, Any]) -> dict[str, Any]:
    value = input_payload.get("openai_sampling")
    return dict(value) if isinstance(value, dict) else {}


def _served_model_id(profile: ModelProfile) -> str:
    for value in (profile.routing.get("served_model_name"), profile.routing.get("runner_model_id")):
        if isinstance(value, str) and value:
            return value
    pipeline = profile.routing.get("pipeline")
    if isinstance(pipeline, dict):
        for key in ("served_model_name", "runner_model_id"):
            value = pipeline.get(key)
            if isinstance(value, str) and value:
                return value
    return profile.model_id


def _usage_from_response(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage")
    return dict(usage) if isinstance(usage, dict) else {}


def _estimate_text_tokens(text: str) -> int:
    return max(0, len(text.encode("utf-8")) // 4)


def _copy_optional_dict(value: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _json_env(name: str) -> dict[str, Any]:
    value = os.environ.get(name)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _compatible_completion_cohort(requests: list[InferenceRequest]) -> bool:
    if not requests:
        return False
    first = requests[0]
    if first.chat:
        return False
    first_extra = kv_cache_extra_body(first.input)
    first_sampling = openai_sampling_controls(first.input)
    first_contract = dict(first.output_contract or {})
    for item in requests:
        if item.chat:
            return False
        if item.max_output_tokens != first.max_output_tokens:
            return False
        if item.thinking_budget_tokens != first.thinking_budget_tokens:
            return False
        if float(item.temperature) != float(first.temperature):
            return False
        if dict(item.output_contract or {}) != first_contract:
            return False
        if kv_cache_extra_body(item.input) != first_extra:
            return False
        if openai_sampling_controls(item.input) != first_sampling:
            return False
    return True


def _payload_has_strict_kv_load(payload: dict[str, Any]) -> bool:
    extra = payload.get("extra_body")
    if not isinstance(extra, dict):
        return False
    plan = extra.get("ds4_kv_cache")
    if not isinstance(plan, dict):
        return False
    load = plan.get("load")
    if not isinstance(load, dict):
        return False
    if str(load.get("mode") or "skip") not in {"prefer", "require"}:
        return False
    miss_policy = str(plan.get("miss_policy") or "")
    return str(load.get("mode") or "") == "require" or miss_policy == "fail"


def _common_prompt_prefix(requests: list[InferenceRequest]) -> str | None:
    shared_values = [
        item.input.get("shared_prefix")
        for item in requests
        if isinstance(item.input.get("shared_prefix"), str)
    ]
    if len(shared_values) == len(requests) and shared_values:
        first = str(shared_values[0])
        if first and all(str(value) == first for value in shared_values):
            return first
    prompts = [request_prompt(item) for item in requests]
    if not prompts:
        return None
    prefix = os.path.commonprefix(prompts)
    if not prefix:
        return None
    if prefix[-1].isspace():
        return prefix
    cuts = [prefix.rfind(ch) for ch in (" ", "\n", "\t")]
    cut = max(cuts)
    if cut <= 0:
        return None
    return prefix[: cut + 1]


def _usage_for_coalesced_choice(data: dict[str, Any], choice: dict[str, Any], index: int, count: int) -> dict[str, Any]:
    usage = choice.get("usage")
    if isinstance(usage, dict):
        return dict(usage)
    total = data.get("usage")
    if not isinstance(total, dict) or count <= 0:
        return {}
    out: dict[str, Any] = {}
    for key, value in total.items():
        if isinstance(value, int):
            base = value // count
            remainder = value % count
            out[key] = base + (1 if index < remainder else 0)
        elif isinstance(value, float):
            out[key] = value / count
    return out


def _completed_error(completed: Any, host: str) -> str:
    detail = str(getattr(completed, "stderr", "") or getattr(completed, "stdout", "") or "").strip()[-4000:]
    if not detail:
        return f"ssh to {host} exited {getattr(completed, 'returncode', 'unknown')} with empty stdout/stderr"
    return f"ssh to {host} exited {getattr(completed, 'returncode', 'unknown')}: {detail}"


def _merge_extra_body(payload: dict[str, Any], extra_body: dict[str, Any]) -> None:
    if not extra_body:
        return
    existing = payload.get("extra_body")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(extra_body)
    payload["extra_body"] = merged
