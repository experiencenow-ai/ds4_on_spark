from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
from typing import Any, Callable, Iterator, Protocol
from urllib import error, request as urlrequest

from .builders import model_batch_payload, request_messages, request_prompt
from .cohort_safety import coalesced_completion_token_budget, coalesced_failure_should_bisect, mark_coalesced_split, prompt_token_estimate
from .jit_kv import build_prefetch_payload, disable_strict_kv, run_prefetch
from .kv_cache import kv_cache_extra_body, kv_cache_vllm_request_fields
from .profiles import ModelProfile
from .runner_payloads import merge_payload_extra_body, merge_request_extra_body, requests_need_client_stream
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
        chat_batch_endpoint: str = "/v1/chat/completions/batch",
        completion_endpoint: str = "/v1/completions",
        default_extra_body: dict[str, Any] | None = None,
        jit_kv_circuit: Any | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("DS4_OPENAI_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("DS4_OPENAI_API_KEY", "")
        self.timeout_s = timeout_s
        self.chat_endpoint = chat_endpoint
        self.chat_batch_endpoint = chat_batch_endpoint
        self.completion_endpoint = completion_endpoint
        self.default_extra_body = dict(default_extra_body or {})
        self.jit_kv_circuit = jit_kv_circuit

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

    def run_many_chat(self, requests: list[InferenceRequest], profile: ModelProfile) -> dict[str, dict] | None:
        request_list = list(requests)
        if not request_list or not all(item.chat for item in request_list):
            return None
        minimum = max(2, int(os.environ.get("DS4_PIPELINE_CHAT_COHORT_MIN", "2") or "2"))
        if len(request_list) < minimum:
            return None
        max_cohort = _completion_effective_max_cohort(profile)
        token_budget = coalesced_completion_token_budget()
        payloads: list[tuple[list[InferenceRequest], dict[str, Any]]] = []
        chunks = _completion_cohort_chunks(request_list, max_cohort=max_cohort, token_budget=token_budget)
        for chunk in chunks:
            payload = _coalesced_chat_payload(chunk, profile, self.default_extra_body)
            if payload is None:
                return None
            payloads.append((chunk, payload))
        out: dict[str, dict] = {}
        concurrency = _completion_chunk_concurrency(profile)
        if concurrency > 1 and len(payloads) > 1:
            with ThreadPoolExecutor(max_workers=min(concurrency, len(payloads))) as executor:
                futures = [
                    executor.submit(self._run_chat_chunk, chunk, profile, payload, original_batch_size=len(chunk))
                    for chunk, payload in payloads
                ]
                for future in as_completed(futures):
                    out.update(future.result())
        else:
            for chunk, payload in payloads:
                out.update(self._run_chat_chunk(chunk, profile, payload, original_batch_size=len(chunk)))
        if len(chunks) > 1:
            _mark_coalesced_chat_planned_split(out, original_batch_size=len(request_list), chunk_count=len(chunks), max_cohort=max_cohort, concurrency=concurrency)
        return out

    def _run_chat_chunk(self, chunk: list[InferenceRequest], profile: ModelProfile, payload: dict[str, Any], *, original_batch_size: int) -> dict[str, dict]:
        started = time.time()
        try:
            prefetch_info = _maybe_prestage_common_kv_prefix(self, payload, chunk)
            data = self._post_json(self.chat_batch_endpoint, payload)
            out = _coalesced_chat_results(chunk, profile, data, base_url=self.base_url, endpoint=self.chat_batch_endpoint, started=started, prefetch_info=prefetch_info)
            if original_batch_size != len(chunk):
                mark_coalesced_split(out, original_batch_size=original_batch_size)
            return out
        except Exception as exc:
            return {
                item.request_id: self._transport_failure(item, profile, started, str(exc), endpoint=self.chat_batch_endpoint, coalesced_batch_size=len(chunk))
                for item in chunk
            }

    def run_many_completion(self, requests: list[InferenceRequest], profile: ModelProfile) -> dict[str, dict] | None:
        request_list = list(requests)
        minimum = max(2, int(os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_MIN", "2") or "2"))
        if len(request_list) < minimum:
            return None
        max_cohort = _completion_effective_max_cohort(profile)
        token_budget = coalesced_completion_token_budget()
        payloads: list[tuple[list[InferenceRequest], dict[str, Any]]] = []
        chunks = _completion_cohort_chunks(request_list, max_cohort=max_cohort, token_budget=token_budget)
        for chunk in chunks:
            payload = _coalesced_completion_payload(chunk, profile, self.default_extra_body)
            if payload is None:
                return None
            payloads.append((chunk, payload))
        out: dict[str, dict] = {}
        concurrency = _completion_chunk_concurrency(profile)
        if concurrency > 1 and len(payloads) > 1:
            with ThreadPoolExecutor(max_workers=min(concurrency, len(payloads))) as executor:
                futures = [
                    executor.submit(self._run_completion_chunk, chunk, profile, payload, original_batch_size=len(chunk))
                    for chunk, payload in payloads
                ]
                for future in as_completed(futures):
                    out.update(future.result())
        else:
            for chunk, payload in payloads:
                out.update(self._run_completion_chunk(chunk, profile, payload, original_batch_size=len(chunk)))
        if len(chunks) > 1:
            _mark_coalesced_planned_split(out, original_batch_size=len(request_list), chunk_count=len(chunks), max_cohort=max_cohort, concurrency=concurrency)
        return out

    def _run_completion_chunk(self, chunk: list[InferenceRequest], profile: ModelProfile, payload: dict[str, Any], *, original_batch_size: int) -> dict[str, dict]:
        started = time.time()
        try:
            prefetch_info = _maybe_prestage_common_kv_prefix(self, payload, chunk)
            data = self._post_json(self.completion_endpoint, payload)
            out = _coalesced_completion_results(chunk, profile, data, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, prefetch_info=prefetch_info)
            if original_batch_size != len(chunk):
                mark_coalesced_split(out, original_batch_size=original_batch_size)
            return out
        except Exception as exc:
            if len(chunk) > 1 and _env_bool("DS4_PIPELINE_COMPLETION_BISECT_ON_FAILURE", True) and coalesced_failure_should_bisect(str(exc)):
                midpoint = max(1, len(chunk) // 2)
                out: dict[str, dict] = {}
                for subchunk in (chunk[:midpoint], chunk[midpoint:]):
                    subpayload = _coalesced_completion_payload(subchunk, profile, self.default_extra_body)
                    if subpayload is None:
                        break
                    out.update(self._run_completion_chunk(subchunk, profile, subpayload, original_batch_size=original_batch_size))
                if len(out) == len(chunk):
                    return out
            return {
                item.request_id: self._transport_failure(item, profile, started, str(exc), endpoint=self.completion_endpoint, coalesced_batch_size=len(chunk))
                for item in chunk
            }

    def run_many_completion_incremental(
        self,
        requests: list[InferenceRequest],
        profile: ModelProfile,
        *,
        on_result: Callable[[str, dict[str, Any]], None],
        on_delta: Callable[[str, str, dict[str, Any]], None] | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, dict] | None:
        if not _env_bool("DS4_PIPELINE_COHORT_COMPLETION_STREAMING", True):
            return None
        request_list = list(requests)
        minimum = max(2, int(os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_MIN", "2") or "2"))
        if len(request_list) < minimum:
            return None
        max_cohort = _completion_effective_max_cohort(profile)
        token_budget = coalesced_completion_token_budget()
        chunks = _completion_cohort_chunks(request_list, max_cohort=max_cohort, token_budget=token_budget)
        payloads: list[tuple[list[InferenceRequest], dict[str, Any]]] = []
        for chunk in chunks:
            payload = _coalesced_completion_payload(chunk, profile, self.default_extra_body)
            if payload is None:
                return None
            payload["stream"] = True
            payloads.append((chunk, payload))
        out: dict[str, dict] = {}
        concurrency = _completion_chunk_concurrency(profile)
        if concurrency > 1 and len(payloads) > 1:
            with ThreadPoolExecutor(max_workers=min(concurrency, len(payloads))) as executor:
                futures = [
                    executor.submit(self._run_completion_stream_chunk, chunk, profile, payload, on_result=on_result, on_delta=on_delta, cancel_event=cancel_event)
                    for chunk, payload in payloads
                ]
                for future in as_completed(futures):
                    out.update(future.result())
        else:
            for chunk, payload in payloads:
                out.update(self._run_completion_stream_chunk(chunk, profile, payload, on_result=on_result, on_delta=on_delta, cancel_event=cancel_event))
        if len(chunks) > 1:
            _mark_coalesced_planned_split(out, original_batch_size=len(request_list), chunk_count=len(chunks), max_cohort=max_cohort, concurrency=concurrency)
        return out

    def _run_completion_stream_chunk(self, chunk: list[InferenceRequest], profile: ModelProfile, payload: dict[str, Any], *, on_result: Callable[[str, dict[str, Any]], None], on_delta: Callable[[str, str, dict[str, Any]], None] | None = None, cancel_event: Event | None = None) -> dict[str, dict]:
        started = time.time()
        stream_timeout_s = _completion_stream_wall_timeout_s()
        stream_deadline = (started + stream_timeout_s) if stream_timeout_s > 0 else 0.0
        prefetch_info: dict[str, Any] | None = None
        text_by_index = {idx: "" for idx in range(len(chunk))}
        completed_indexes: set[int] = set()
        out: dict[str, dict] = {}
        timeout_error = ""
        try:
            prefetch_info = _maybe_prestage_common_kv_prefix(self, payload, chunk)
            for event in self._post_sse_json(self.completion_endpoint, payload, cancel_event=cancel_event):
                choices = event.get("choices")
                if not isinstance(choices, list):
                    continue
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    index = _completion_choice_index(choice, len(completed_indexes))
                    if index < 0 or index >= len(chunk) or index in completed_indexes:
                        continue
                    delta = _completion_stream_choice_text(choice)
                    text_by_index[index] += delta
                    if delta and on_delta is not None:
                        on_delta(chunk[index].request_id, delta, {"coalesced_batch_size": len(chunk), "choice_index": index})
                    if choice.get("finish_reason") is None:
                        continue
                    result = _coalesced_stream_result(chunk[index], profile, text_by_index[index], base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=len(chunk), prefetch_info=_copy_optional_dict(prefetch_info))
                    out[chunk[index].request_id] = result
                    completed_indexes.add(index)
                    on_result(chunk[index].request_id, result)
                if stream_deadline > 0 and time.time() >= stream_deadline and len(completed_indexes) < len(chunk):
                    timeout_error = f"coalesced completion stream wall timeout after {stream_timeout_s:.3f}s"
                    break
                if cancel_event is not None and cancel_event.is_set() and len(completed_indexes) < len(chunk):
                    timeout_error = "coalesced completion stream cancelled"
                    break
        except Exception as exc:
            for index, item in enumerate(chunk):
                if index in completed_indexes:
                    continue
                result = self._transport_failure(item, profile, started, str(exc), endpoint=self.completion_endpoint, coalesced_batch_size=len(chunk))
                out[item.request_id] = result
                completed_indexes.add(index)
                on_result(item.request_id, result)
            return out
        for index, item in enumerate(chunk):
            if index in completed_indexes:
                continue
            if timeout_error:
                result = _coalesced_failure(item, profile, self.base_url, self.completion_endpoint, started, len(chunk), timeout_error)
            else:
                text = text_by_index.get(index) or ""
                result = _coalesced_stream_result(item, profile, text, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=len(chunk), prefetch_info=_copy_optional_dict(prefetch_info)) if text else _coalesced_failure(item, profile, self.base_url, self.completion_endpoint, started, len(chunk), "stream ended before this coalesced completion finished")
            out[item.request_id] = result
            completed_indexes.add(index)
            on_result(item.request_id, result)
        return out

    def _transport_failure(self, request: InferenceRequest, profile: ModelProfile, started: float, error: str, *, endpoint: str | None = None, coalesced_batch_size: int | None = None) -> dict:
        result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": error}, sort_keys=True), status="transport_failed")
        result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6), "error": error}
        if endpoint is not None:
            result["transport"]["endpoint"] = endpoint
        if coalesced_batch_size is not None:
            result["transport"]["coalesced_batch_size"] = coalesced_batch_size
        return result

    def _post_json(self, endpoint: str, payload: dict[str, Any], *, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        headers.update(extra_headers or {})
        req = urlrequest.Request(self.base_url + endpoint, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s) as response:
                text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        return json.loads(text)

    def _post_sse_json(self, endpoint: str, payload: dict[str, Any], *, cancel_event: Event | None = None) -> Iterator[dict[str, Any]]:
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
                if cancel_event is not None and cancel_event.is_set():
                    break
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
            if cancel_event is not None and cancel_event.is_set():
                return
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
        jit_kv_circuit: Any | None = None,
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
        self.jit_kv_circuit = jit_kv_circuit

    def run_one(self, request: InferenceRequest, profile: ModelProfile) -> dict:
        return self.run_one_on_node(request, profile, None)

    def run_one_on_node(self, request: InferenceRequest, profile: ModelProfile, node_id: str | None) -> dict:
        return self._runner_for(profile, node_id).run_one(request, profile)

    def run_many_on_node(self, requests: list[InferenceRequest], profile: ModelProfile, node_id: str | None, *, concurrency: int = 1) -> dict[str, dict]:
        request_list = list(requests)
        if not request_list:
            return {}
        worker_count = max(1, min(int(concurrency), len(request_list)))
        runner = self._runner_for(profile, node_id)
        if _env_bool("DS4_PIPELINE_COHORT_CHAT_BATCH", True):
            coalesced_chat = runner.run_many_chat(request_list, profile)
            if coalesced_chat is not None:
                return coalesced_chat
        if _env_bool("DS4_PIPELINE_COHORT_COMPLETIONS", True):
            coalesced = runner.run_many_completion(request_list, profile)
            if coalesced is not None:
                return coalesced
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
        on_delta: Callable[[str, str, dict[str, Any]], None] | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, dict]:
        request_list = list(requests)
        if not request_list:
            return {}
        worker_count = max(1, min(int(concurrency), len(request_list)))
        runner = self._runner_for(profile, node_id)
        client_stream = requests_need_client_stream(request_list)
        if not client_stream and _env_bool("DS4_PIPELINE_COHORT_CHAT_BATCH", True):
            coalesced_chat = runner.run_many_chat(request_list, profile)
            if coalesced_chat is not None:
                for request_id, result in coalesced_chat.items():
                    on_result(request_id, result)
                return coalesced_chat
        if _env_bool("DS4_PIPELINE_COHORT_COMPLETIONS", True):
            internal_stream = client_stream or _internal_stream_nonclient_cohort(request_list)
            if internal_stream:
                coalesced = runner.run_many_completion_incremental(request_list, profile, on_result=on_result, on_delta=on_delta if client_stream else None, cancel_event=cancel_event)
                if coalesced is not None:
                    return coalesced
            coalesced = runner.run_many_completion(request_list, profile)
            if coalesced is not None:
                for request_id, result in coalesced.items():
                    on_result(request_id, result)
                return coalesced
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

    def _runner_for(self, profile: ModelProfile, node_id: str | None) -> OpenAICompatibleRunner:
        return OpenAICompatibleRunner(
            base_url=self._base_url(profile, node_id),
            api_key=self.api_key,
            timeout_s=self.timeout_s,
            default_extra_body=self.default_extra_body,
            jit_kv_circuit=self.jit_kv_circuit,
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
            content = message.get("content")
            if content is not None:
                return strip_visible_thinking(str(content))
            for key in ("reasoning_content", "reasoning"):
                if message.get(key) is not None:
                    return strip_visible_thinking(str(message.get(key)))
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


def _coalesced_completion_payload(requests: list[InferenceRequest], profile: ModelProfile, default_extra_body: dict[str, Any]) -> dict[str, Any] | None:
    prompts: list[str] = []
    shared: dict[str, Any] | None = None
    for item in requests:
        if item.chat:
            return None
        payload = _openai_payload(item, profile)
        _merge_extra_body(payload, default_extra_body)
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return None
        comparable = dict(payload)
        comparable.pop("prompt", None)
        if shared is None:
            shared = comparable
        elif comparable != shared:
            return None
        prompts.append(prompt)
    if shared is None:
        return None
    payload = dict(shared)
    payload["prompt"] = prompts
    return payload

def _coalesced_chat_payload(requests: list[InferenceRequest], profile: ModelProfile, default_extra_body: dict[str, Any]) -> dict[str, Any] | None:
    conversations: list[list[dict[str, str]]] = []
    shared: dict[str, Any] | None = None
    for item in requests:
        if not item.chat:
            return None
        payload = _openai_payload(item, profile)
        if payload.get("tools") is not None or payload.get("tool_choice") is not None:
            return None
        _merge_extra_body(payload, default_extra_body)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        comparable = dict(payload)
        comparable.pop("messages", None)
        if shared is None:
            shared = comparable
        elif comparable != shared:
            return None
        conversations.append(messages)
    if shared is None:
        return None
    payload = dict(shared)
    payload["messages"] = conversations
    return payload

def _maybe_prestage_common_kv_prefix(runner: OpenAICompatibleRunner, payload: dict[str, Any], requests: list[InferenceRequest]) -> dict[str, Any] | None:
    if not _env_bool("DS4_PIPELINE_PRESTAGE_COMMON_KV_PREFIX", True):
        return None
    if not _payload_has_strict_kv_load(payload):
        return None
    circuit = getattr(runner, "jit_kv_circuit", None)
    if circuit is not None and not circuit.allow_prefetch():
        disable_strict_kv(payload)
        return {
            "strategy": "jit-kv-circuit-open-cold-dispatch",
            "cold_dispatch": True,
        }
    prefix = _common_prompt_prefix(requests)
    min_chars = _env_int("DS4_PIPELINE_PRESTAGE_COMMON_PREFIX_MIN_CHARS", 1024)
    if prefix is None or len(prefix) < max(1, min_chars):
        return None
    max_tokens = max(1, _env_int("DS4_PIPELINE_PRESTAGE_MAX_TOKENS", 1))
    prefetch_payload = build_prefetch_payload(payload, prefix=prefix, max_tokens=max_tokens)
    return run_prefetch(runner=runner, payload=payload, prefetch_payload=prefetch_payload, prefix_len=len(prefix), max_tokens=max_tokens, started=time.time(), circuit=circuit)


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
    cut = max(prefix.rfind(ch) for ch in (" ", "\n", "\t"))
    if cut <= 0:
        return None
    return prefix[: cut + 1]


def _completion_cohort_chunks(requests: list[InferenceRequest], *, max_cohort: int, token_budget: int) -> list[list[InferenceRequest]]:
    chunks: list[list[InferenceRequest]] = []
    current: list[InferenceRequest] = []
    current_tokens = 0
    max_cohort = max(1, int(max_cohort))
    token_budget = max(0, int(token_budget))
    for item in requests:
        estimate = _completion_request_token_estimate(item)
        would_exceed_size = len(current) >= max_cohort
        would_exceed_tokens = token_budget > 0 and current and (current_tokens + estimate) > token_budget
        if would_exceed_size or would_exceed_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(item)
        current_tokens += estimate
    if current:
        chunks.append(current)
    return chunks


def _completion_effective_max_cohort(profile: ModelProfile) -> int:
    max_cohort = max(1, _env_int("DS4_PIPELINE_COMPLETION_COHORT_MAX", 512))
    if not _profile_uses_pipeline(profile):
        return max_cohort
    pp_safe = _env_int("DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX", 0)
    if pp_safe <= 0:
        return max_cohort
    return max(1, min(max_cohort, pp_safe))


def _completion_chunk_concurrency(profile: ModelProfile) -> int:
    if not _profile_uses_pipeline(profile):
        return 1
    return max(1, _env_int("DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY", 4))


def _completion_stream_wall_timeout_s() -> float:
    return max(0.0, _env_float("DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S", 0.0))


def _profile_uses_pipeline(profile: ModelProfile) -> bool:
    backend = str(profile.backend).lower()
    if "pipeline" in backend:
        return True
    pipeline = profile.routing.get("pipeline")
    return isinstance(pipeline, dict) and bool(pipeline)


def _mark_coalesced_planned_split(out: dict[str, dict], *, original_batch_size: int, chunk_count: int, max_cohort: int, concurrency: int) -> None:
    for result in out.values():
        transport: dict[str, Any] = result.setdefault("transport", {})
        transport["coalesced_completion_planned_split"] = True
        transport["original_coalesced_batch_size"] = original_batch_size
        transport["coalesced_completion_chunk_count"] = chunk_count
        transport["coalesced_completion_effective_max_cohort"] = max_cohort
        transport["coalesced_completion_chunk_concurrency"] = concurrency

def _mark_coalesced_chat_planned_split(out: dict[str, dict], *, original_batch_size: int, chunk_count: int, max_cohort: int, concurrency: int) -> None:
    for result in out.values():
        transport: dict[str, Any] = result.setdefault("transport", {})
        transport["coalesced_chat_planned_split"] = True
        transport["original_coalesced_batch_size"] = original_batch_size
        transport["coalesced_chat_chunk_count"] = chunk_count
        transport["coalesced_chat_effective_max_cohort"] = max_cohort
        transport["coalesced_chat_chunk_concurrency"] = concurrency


def _completion_request_token_estimate(request: InferenceRequest) -> int:
    prompt_tokens = _completion_prompt_token_hint(request)
    if prompt_tokens is None:
        prompt_tokens = prompt_token_estimate(request_prompt(request))
    output_tokens = int(request.max_output_tokens) if _env_bool("DS4_PIPELINE_COMPLETION_COHORT_BUDGET_INCLUDE_OUTPUT", True) else 0
    return max(1, int(prompt_tokens) + output_tokens)


def _completion_prompt_token_hint(request: InferenceRequest) -> int | None:
    if not _env_bool("DS4_PIPELINE_COMPLETION_USE_TOKEN_HINTS", True):
        return None
    sources: list[dict[str, Any]] = []
    if isinstance(request.input, dict):
        sources.append(request.input)
        benchmark_shape = request.input.get("benchmark_shape")
        if isinstance(benchmark_shape, dict):
            sources.append(benchmark_shape)
    raw_input = request.raw.get("input") if isinstance(request.raw, dict) else None
    if isinstance(raw_input, dict) and raw_input is not request.input:
        sources.append(raw_input)
        benchmark_shape = raw_input.get("benchmark_shape")
        if isinstance(benchmark_shape, dict):
            sources.append(benchmark_shape)
    for source in sources:
        for key in ("estimated_prompt_tokens", "estimated_input_tokens", "prompt_tokens", "input_tokens"):
            value = source.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and int(value) > 0:
                return int(value)
            if isinstance(value, str):
                try:
                    parsed = int(value)
                except ValueError:
                    continue
                if parsed > 0:
                    return parsed
    return None


def _coalesced_completion_results(
    requests: list[InferenceRequest],
    profile: ModelProfile,
    data: dict[str, Any],
    *,
    base_url: str,
    endpoint: str,
    started: float,
    prefetch_info: dict[str, Any] | None = None,
) -> dict[str, dict]:
    choices = data.get("choices")
    if not isinstance(choices, list):
        return {
            item.request_id: _coalesced_failure(item, profile, base_url, endpoint, started, len(requests), "coalesced completion response missing choices")
            for item in requests
        }
    by_index: dict[int, dict[str, Any]] = {}
    for position, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        raw_index = choice.get("index", position)
        index = int(raw_index) if isinstance(raw_index, (int, float)) else position
        if 0 <= index < len(requests):
            by_index[index] = choice
    out: dict[str, dict] = {}
    for index, item in enumerate(requests):
        choice = by_index.get(index)
        if choice is None:
            out[item.request_id] = _coalesced_failure(item, profile, base_url, endpoint, started, len(requests), f"coalesced completion response missing choice index {index}")
            continue
        result = make_result(request=item, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=extract_openai_completion_text({"choices": [choice]}))
        result["usage"].update(_coalesced_usage(data, choice, item, len(requests)))
        result["transport"] = {"base_url": base_url, "endpoint": endpoint, "duration_s": round(time.time() - started, 6), "coalesced_completion_batch": True, "coalesced_batch_size": len(requests), "batch_size": len(requests)}
        if prefetch_info is not None:
            result["transport"]["kv_prestage"] = dict(prefetch_info)
        out[item.request_id] = result
    return out

def _coalesced_chat_results(
    requests: list[InferenceRequest],
    profile: ModelProfile,
    data: dict[str, Any],
    *,
    base_url: str,
    endpoint: str,
    started: float,
    prefetch_info: dict[str, Any] | None = None,
) -> dict[str, dict]:
    choices = data.get("choices")
    if not isinstance(choices, list):
        return {
            item.request_id: _coalesced_failure(item, profile, base_url, endpoint, started, len(requests), "coalesced chat response missing choices")
            for item in requests
        }
    by_index: dict[int, dict[str, Any]] = {}
    for position, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        raw_index = choice.get("index", position)
        index = int(raw_index) if isinstance(raw_index, (int, float)) else position
        if 0 <= index < len(requests):
            by_index[index] = choice
    out: dict[str, dict] = {}
    for index, item in enumerate(requests):
        choice = by_index.get(index)
        if choice is None:
            out[item.request_id] = _coalesced_failure(item, profile, base_url, endpoint, started, len(requests), f"coalesced chat response missing choice index {index}")
            continue
        result = make_result(request=item, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=extract_openai_chat_text({"choices": [choice]}))
        result["usage"].update(_coalesced_usage(data, choice, item, len(requests)))
        result["transport"] = {"base_url": base_url, "endpoint": endpoint, "duration_s": round(time.time() - started, 6), "coalesced_chat_batch": True, "coalesced_batch_size": len(requests), "batch_size": len(requests)}
        if prefetch_info is not None:
            result["transport"]["kv_prestage"] = dict(prefetch_info)
        out[item.request_id] = result
    return out


def _completion_choice_index(choice: dict[str, Any], fallback: int) -> int:
    raw = choice.get("index", fallback)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(fallback)


def _coalesced_stream_result(
    request: InferenceRequest,
    profile: ModelProfile,
    text: str,
    *,
    base_url: str,
    endpoint: str,
    started: float,
    batch_size: int,
    prefetch_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
    if _forced_output_request(request):
        result["usage"].update({"completion_tokens": request.max_output_tokens, "completion_tokens_forced": True})
    else:
        result["usage"].update({"completion_tokens": _estimate_text_tokens(text), "completion_tokens_estimated": True})
    result["transport"] = {
        "base_url": base_url,
        "endpoint": endpoint,
        "duration_s": round(time.time() - started, 6),
        "coalesced_completion_batch": True,
        "coalesced_completion_streaming": True,
        "coalesced_batch_size": batch_size,
        "batch_size": batch_size,
    }
    if prefetch_info is not None:
        result["transport"]["kv_prestage"] = dict(prefetch_info)
    return result


def _coalesced_failure(request: InferenceRequest, profile: ModelProfile, base_url: str, endpoint: str, started: float, batch_size: int, error: str) -> dict:
    result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": error}, sort_keys=True), status="transport_failed")
    result["transport"] = {"base_url": base_url, "endpoint": endpoint, "duration_s": round(time.time() - started, 6), "coalesced_batch_size": batch_size, "error": error}
    return result


def _coalesced_usage(data: dict[str, Any], choice: dict[str, Any], request: InferenceRequest, batch_size: int) -> dict[str, Any]:
    usage = choice.get("usage")
    if isinstance(usage, dict):
        return dict(usage)
    out: dict[str, Any] = {}
    batch_usage = data.get("usage")
    if _forced_output_request(request):
        out["completion_tokens"] = request.max_output_tokens
    elif isinstance(batch_usage, dict) and isinstance(batch_usage.get("completion_tokens"), (int, float)) and batch_size > 0:
        out["completion_tokens"] = max(0, int(batch_usage["completion_tokens"]) // batch_size)
    if isinstance(batch_usage, dict) and isinstance(batch_usage.get("prompt_tokens"), (int, float)) and batch_size > 0:
        out["prompt_tokens"] = max(0, int(batch_usage["prompt_tokens"]) // batch_size)
    if "prompt_tokens" in out and "completion_tokens" in out:
        out["total_tokens"] = int(out["prompt_tokens"]) + int(out["completion_tokens"])
    return out


def _forced_output_request(request: InferenceRequest) -> bool:
    raw = request.input.get("openai")
    if not isinstance(raw, dict):
        raw = request.input.get("openai_sampling")
    if not isinstance(raw, dict):
        return False
    if not bool(raw.get("ignore_eos")):
        return False
    try:
        min_tokens = int(raw.get("min_tokens") or 0)
    except (TypeError, ValueError):
        return False
    return min_tokens >= int(request.max_output_tokens)


def _internal_stream_nonclient_cohort(requests: list[InferenceRequest]) -> bool:
    raw = os.environ.get("DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS")
    if raw is not None:
        return _env_bool("DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS", True)
    mode = os.environ.get("DS4_PIPELINE_INTERNAL_STREAM_MODE", "auto").strip().lower()
    if mode in {"1", "true", "yes", "on", "always"}:
        return True
    if mode in {"0", "false", "no", "off", "never"}:
        return False
    if mode not in {"", "auto"}:
        raise ValueError("DS4_PIPELINE_INTERNAL_STREAM_MODE must be auto, always, or never")
    return not requests or not all(_forced_output_request(item) for item in requests)


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
    max_tokens = max(1, int(request.max_output_tokens) + int(request.thinking_budget_tokens))
    if request.chat:
        payload: dict[str, Any] = {
            "model": model,
            "messages": request_messages(request),
            "temperature": request.temperature,
            "max_tokens": max_tokens,
        }
    else:
        prompt = request_prompt(request)
        payload = {
            "model": model,
            "prompt": prompt,
            "temperature": request.temperature,
            "max_tokens": max_tokens,
        }
    _merge_openai_request_fields(payload, request)
    sampling = openai_sampling_controls(request.input)
    if sampling:
        payload.update(sampling)
    merge_request_extra_body(payload, request, profile)
    extra_body = kv_cache_extra_body(request.input)
    if extra_body:
        payload.update(kv_cache_vllm_request_fields(request.input))
        payload["extra_body"] = {**dict(payload.get("extra_body") or {}), **extra_body}
    return payload


def openai_sampling_controls(input_payload: dict[str, Any]) -> dict[str, Any]:
    value = input_payload.get("openai_sampling")
    return dict(value) if isinstance(value, dict) else {}


def _served_model_id(profile: ModelProfile) -> str:
    for key in _served_model_override_keys(profile):
        override = _served_model_overrides().get(key)
        if isinstance(override, str) and override:
            return override
    for value in (profile.routing.get("served_model_name"), profile.routing.get("runner_model_id")):
        if isinstance(value, str) and value:
            return _served_model_with_pipeline_suffix(value)
    pipeline = profile.routing.get("pipeline")
    if isinstance(pipeline, dict):
        for key in ("served_model_name", "runner_model_id"):
            value = pipeline.get(key)
            if isinstance(value, str) and value:
                return _served_model_with_pipeline_suffix(value)
    return _served_model_with_pipeline_suffix(profile.model_id)


def _served_model_override_keys(profile: ModelProfile) -> tuple[str, ...]:
    keys = [profile.profile_id, profile.model_id]
    pipeline = profile.routing.get("pipeline")
    if isinstance(pipeline, dict):
        for key in ("service_id", "served_model_name", "runner_model_id"):
            value = pipeline.get(key)
            if isinstance(value, str) and value:
                keys.append(value)
    for key in ("pipeline_service_id", "served_model_name", "runner_model_id"):
        value = profile.routing.get(key)
        if isinstance(value, str) and value:
            keys.append(value)
    return tuple(dict.fromkeys(keys))


def _served_model_overrides() -> dict[str, str]:
    raw = os.environ.get("DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON", "")
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("DS4_PIPELINE_SERVED_MODEL_OVERRIDES_JSON must be an object")
    return {str(key): str(value) for key, value in data.items() if str(value)}


def _served_model_with_pipeline_suffix(model_id: str) -> str:
    if not _env_bool_local("DS4_PIPELINE_AUTO_SERVED_MODEL_PP_SUFFIX", True):
        return model_id
    stage_count = _pipeline_node_count_override()
    if stage_count < 1:
        return model_id
    for marker in ("-pp", "_pp"):
        prefix, sep, suffix = model_id.rpartition(marker)
        if sep and suffix.isdigit():
            return prefix + marker + str(stage_count)
    return model_id


def _pipeline_node_count_override() -> int:
    raw = os.environ.get("DS4_PIPELINE_NODES", "")
    nodes = [item.strip() for item in raw.split(",") if item.strip()]
    return len(nodes)


def _env_bool_local(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


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
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _completed_error(completed: Any, host: str) -> str:
    detail = str(getattr(completed, "stderr", "") or getattr(completed, "stdout", "") or "").strip()[-4000:]
    if not detail:
        return f"ssh to {host} exited {getattr(completed, 'returncode', 'unknown')} with empty stdout/stderr"
    return f"ssh to {host} exited {getattr(completed, 'returncode', 'unknown')}: {detail}"


def _merge_extra_body(payload: dict[str, Any], extra_body: dict[str, Any]) -> None:
    merge_payload_extra_body(payload, extra_body)


OPENAI_REQUEST_FIELDS = {
    "ignore_eos",
    "include_stop_str_in_output",
    "min_tokens",
    "repetition_penalty",
    "seed",
    "skip_special_tokens",
    "stop",
    "stop_token_ids",
    "top_k",
    "top_p",
    "truncate_prompt_tokens",
}


def _merge_openai_request_fields(payload: dict[str, Any], request: InferenceRequest) -> None:
    raw = request.input.get("openai")
    if not isinstance(raw, dict):
        return
    for key in OPENAI_REQUEST_FIELDS:
        if key in raw and raw[key] is not None:
            payload[key] = raw[key]
