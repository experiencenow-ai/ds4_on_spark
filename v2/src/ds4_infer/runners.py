from __future__ import annotations

import hashlib
import json
import os
import re
import select
import socket
from pathlib import Path
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event
from typing import Any, Callable, Iterator, Protocol
from urllib import error, request as urlrequest

from .builders import model_batch_payload, request_messages, request_prompt
from .api_chat_render import rendered_chat_prompt_from_input
from .chat_streaming import run_parallel_chat_stream
from .cohort_safety import coalesced_completion_token_budget, coalesced_failure_should_bisect, mark_coalesced_split, prompt_token_estimate
from .coalesced_groups import plan_compatible_payload_groups
from .jit_kv import build_prefetch_payload, disable_strict_kv, run_prefetch
from .kv_cache import kv_cache_extra_body, kv_cache_vllm_request_fields
from .profiles import ModelProfile
from .runner_payloads import AUTO_KV_BATCH_SUPPRESSED_KEY, maybe_suppress_generated_auto_kv_for_cohort, merge_payload_extra_body, merge_request_extra_body, requests_need_client_stream
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
            if request.chat and _chat_cohort_transport(profile) in {"completion_prompts", "parallel_completion_prompts"}:
                payload = _openai_completion_prompt_payload(request, profile, prompt=_chat_completion_prompt(request, profile))
                _merge_extra_body(payload, self.default_extra_body)
                data = self._post_json(self.completion_endpoint, payload)
                text = extract_openai_completion_text(data)
                endpoint = self.completion_endpoint
                chat_as_completion = True
            elif request.chat:
                payload = _openai_payload(request, profile)
                _merge_extra_body(payload, self.default_extra_body)
                data = self._post_json(self.chat_endpoint, payload)
                text = extract_openai_chat_text(data)
                endpoint = self.chat_endpoint
                chat_as_completion = False
            else:
                payload = _openai_payload(request, profile)
                _merge_extra_body(payload, self.default_extra_body)
                data = self._post_json(self.completion_endpoint, payload)
                text = extract_openai_completion_text(data)
                endpoint = self.completion_endpoint
                chat_as_completion = False
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(data))
            result["transport"] = {"base_url": self.base_url, "endpoint": endpoint, "duration_s": round(time.time() - started, 6)}
            if chat_as_completion:
                result["transport"]["chat_as_completion_prompts"] = True
            return result
        except Exception as exc:
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": str(exc)}, sort_keys=True), status="transport_failed")
            result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6), "error": str(exc)}
            return result

    def run_many_chat(self, requests: list[InferenceRequest], profile: ModelProfile) -> dict[str, dict] | None:
        request_list = list(requests)
        if _chat_cohort_transport(profile) == "completion_prompts":
            return self._run_many_chat_as_completion(request_list, profile)
        if _chat_cohort_transport(profile) == "parallel_completion_prompts":
            return self._run_many_chat_completion_parallel(request_list, profile)
        if _chat_cohort_transport(profile) == "parallel_chat_completions":
            return self._run_many_chat_parallel(request_list, profile)
        plan = self._chat_batch_plan(request_list, profile)
        if plan is None:
            return None
        chunks, payloads, max_cohort, concurrency = plan
        out: dict[str, dict] = {}
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

    def run_many_chat_incremental(
        self,
        requests: list[InferenceRequest],
        profile: ModelProfile,
        *,
        on_result: Callable[[str, dict[str, Any]], None],
        cancel_event: Event | None = None,
    ) -> dict[str, dict] | None:
        request_list = list(requests)
        if _chat_cohort_transport(profile) == "completion_prompts":
            out = self._run_many_chat_as_completion(request_list, profile)
            if out is None:
                return None
            for request_id, result in out.items():
                on_result(request_id, result)
            return out
        if _chat_cohort_transport(profile) == "parallel_completion_prompts":
            return self._run_many_chat_completion_parallel(
                request_list,
                profile,
                on_result=on_result,
                cancel_event=cancel_event,
            )
        if _chat_cohort_transport(profile) == "parallel_chat_completions":
            return self._run_many_chat_parallel(
                request_list,
                profile,
                on_result=on_result,
                cancel_event=cancel_event,
            )
        plan = self._chat_batch_plan(request_list, profile)
        if plan is None:
            return None
        chunks, payloads, max_cohort, concurrency = plan
        out: dict[str, dict] = {}

        def publish(chunk_out: dict[str, dict]) -> None:
            if len(chunks) > 1:
                _mark_coalesced_chat_planned_split(chunk_out, original_batch_size=len(request_list), chunk_count=len(chunks), max_cohort=max_cohort, concurrency=concurrency)
            out.update(chunk_out)
            for request_id, result in chunk_out.items():
                on_result(request_id, result)

        if concurrency > 1 and len(payloads) > 1:
            with ThreadPoolExecutor(max_workers=min(concurrency, len(payloads))) as executor:
                futures = [
                    executor.submit(self._run_chat_chunk, chunk, profile, payload, original_batch_size=len(chunk))
                    for chunk, payload in payloads
                ]
                for future in as_completed(futures):
                    publish(future.result())
                    if cancel_event is not None and cancel_event.is_set():
                        break
        else:
            for chunk, payload in payloads:
                if cancel_event is not None and cancel_event.is_set():
                    break
                publish(self._run_chat_chunk(chunk, profile, payload, original_batch_size=len(chunk)))
        return out

    def _run_many_chat_completion_parallel(
        self,
        requests: list[InferenceRequest],
        profile: ModelProfile,
        *,
        on_result: Callable[[str, dict[str, Any]], None] | None = None,
        cancel_event: Event | None = None,
    ) -> dict[str, dict] | None:
        request_list = list(requests)
        if not request_list or not all(item.chat for item in request_list):
            return None
        minimum = _cancelable_cohort_minimum("DS4_PIPELINE_CHAT_COHORT_MIN", cancel_event=cancel_event)
        if len(request_list) < minimum:
            return None
        max_cohort = _completion_effective_max_cohort(profile)
        token_budget = coalesced_completion_token_budget()
        chunks = _completion_cohort_chunks(request_list, max_cohort=max_cohort, token_budget=token_budget)
        out: dict[str, dict] = {}
        for chunk in chunks:
            if cancel_event is not None and cancel_event.is_set():
                break
            started = time.time()
            workers = _parallel_chat_concurrency(profile, len(chunk), max_cohort)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(self._run_one_chat_completion_parallel_member, item, profile, started, len(chunk), cancel_event=cancel_event): item
                    for item in chunk
                }
                for future in as_completed(futures):
                    item = futures[future]
                    result = future.result()
                    out[item.request_id] = result
                    if on_result is not None:
                        on_result(item.request_id, result)
                    if cancel_event is not None and cancel_event.is_set():
                        break
        if len(chunks) > 1:
            _mark_coalesced_planned_split(
                out,
                original_batch_size=len(request_list),
                chunk_count=len(chunks),
                max_cohort=max_cohort,
                concurrency=_parallel_chat_concurrency(profile, max(1, max(len(chunk) for chunk in chunks)), max_cohort),
            )
        return out

    def _run_one_chat_completion_parallel_member(
        self,
        request: InferenceRequest,
        profile: ModelProfile,
        started: float,
        batch_size: int,
        *,
        cancel_event: Event | None = None,
    ) -> dict:
        try:
            payload = _openai_completion_prompt_payload(request, profile, prompt=_chat_completion_prompt(request, profile))
            _merge_extra_body(payload, self.default_extra_body)
            if _parallel_completion_prompt_streaming(request):
                return self._run_one_chat_completion_parallel_member_stream(request, profile, payload, started, batch_size, cancel_event=cancel_event)
            data = self._post_json(self.completion_endpoint, payload)
            text = extract_openai_completion_text(data)
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(data))
            result["transport"] = {
                "base_url": self.base_url,
                "endpoint": self.completion_endpoint,
                "duration_s": round(time.time() - started, 6),
                "chat_as_completion_prompts": True,
                "coalesced_chat_parallel_completion": True,
                "coalesced_batch_size": batch_size,
                "batch_size": batch_size,
            }
            return result
        except Exception as exc:
            return self._transport_failure(
                request,
                profile,
                started,
                str(exc),
                endpoint=self.completion_endpoint,
                coalesced_batch_size=batch_size,
            )

    def _run_one_chat_completion_parallel_member_stream(
        self,
        request: InferenceRequest,
        profile: ModelProfile,
        payload: dict[str, Any],
        started: float,
        batch_size: int,
        *,
        cancel_event: Event | None = None,
    ) -> dict:
        payload = dict(payload)
        payload["stream"] = True
        text = ""
        events = self._post_sse_json(self.completion_endpoint, payload, cancel_event=cancel_event)
        try:
            for event in events:
                choices = event.get("choices")
                if not isinstance(choices, list):
                    continue
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    text += _completion_stream_choice_text(choice)
                    stop_text = _answer_marker_early_stop_text(text) if _request_stop_on_answer_marker(request) else None
                    if stop_text is not None:
                        return _parallel_completion_prompt_stream_result(request, profile, stop_text, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=batch_size, early_stop=True)
                    if choice.get("finish_reason") is not None:
                        return _parallel_completion_prompt_stream_result(request, profile, text, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=batch_size, early_stop=False)
        finally:
            close = getattr(events, "close", None)
            if close is not None:
                close()
        if text:
            return _parallel_completion_prompt_stream_result(request, profile, text, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=batch_size, early_stop=False)
        return self._transport_failure(request, profile, started, "parallel completion prompt stream ended before text", endpoint=self.completion_endpoint, coalesced_batch_size=batch_size)

    def _run_many_chat_as_completion(
        self,
        requests: list[InferenceRequest],
        profile: ModelProfile,
    ) -> dict[str, dict] | None:
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
            payload = _coalesced_chat_completion_payload(chunk, profile, self.default_extra_body)
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
        _mark_chat_as_completion(out)
        if len(chunks) > 1:
            _mark_coalesced_planned_split(out, original_batch_size=len(request_list), chunk_count=len(chunks), max_cohort=max_cohort, concurrency=concurrency)
        return out

    def _run_many_chat_parallel(self, requests: list[InferenceRequest], profile: ModelProfile, *, on_result: Callable[[str, dict[str, Any]], None] | None = None, cancel_event: Event | None = None) -> dict[str, dict] | None:
        request_list = list(requests)
        if not request_list or not all(item.chat for item in request_list):
            return None
        minimum = _cancelable_cohort_minimum("DS4_PIPELINE_CHAT_COHORT_MIN", cancel_event=cancel_event)
        if len(request_list) < minimum:
            return None
        max_cohort = _completion_effective_max_cohort(profile)
        token_budget = coalesced_completion_token_budget()
        chunks = _completion_cohort_chunks(request_list, max_cohort=max_cohort, token_budget=token_budget)
        out: dict[str, dict] = {}
        for chunk in chunks:
            if cancel_event is not None and cancel_event.is_set():
                break
            started = time.time()
            workers = _parallel_chat_concurrency(profile, len(chunk), max_cohort)
            executor = ThreadPoolExecutor(max_workers=workers)
            wait_for_workers = True
            try:
                futures = {
                    executor.submit(self._run_one_chat_parallel_member, item, profile, started, len(chunk), cancel_event=cancel_event): item
                    for item in chunk
                }
                for future in as_completed(futures):
                    item = futures[future]
                    result = future.result()
                    out[item.request_id] = result
                    if on_result is not None:
                        on_result(item.request_id, result)
                    if cancel_event is not None and cancel_event.is_set():
                        wait_for_workers = False
                        break
                if cancel_event is not None and cancel_event.is_set():
                    for item in chunk:
                        if item.request_id in out:
                            continue
                        result = self._transport_failure(item, profile, started, "parallel chat stream cancelled", endpoint=self.chat_endpoint, coalesced_batch_size=len(chunk))
                        out[item.request_id] = result
                        if on_result is not None: on_result(item.request_id, result)
                    break
            finally:
                executor.shutdown(wait=wait_for_workers, cancel_futures=not wait_for_workers)
        if len(chunks) > 1:
            concurrency = _parallel_chat_concurrency(profile, max(1, max(len(chunk) for chunk in chunks)), max_cohort)
            _mark_coalesced_chat_planned_split(out, original_batch_size=len(request_list), chunk_count=len(chunks), max_cohort=max_cohort, concurrency=concurrency)
        return out

    def _run_one_chat_parallel_member(
        self,
        request: InferenceRequest,
        profile: ModelProfile,
        started: float,
        batch_size: int,
        *,
        cancel_event: Event | None = None,
    ) -> dict:
        try:
            payload = _openai_payload(request, profile)
            _merge_extra_body(payload, self.default_extra_body)
            if profile.routing.get("parallel_chat_payload_salt") == "extra_body_request_id":
                extra_body = dict(payload.get("extra_body") or {})
                extra_body.setdefault("request_id", request.request_id)
                payload["extra_body"] = extra_body
            if cancel_event is not None and _env_bool("DS4_PIPELINE_PARALLEL_CHAT_INTERNAL_STREAMING", True):
                return run_parallel_chat_stream(
                    post_sse_json=self._post_sse_json,
                    transport_failure=self._transport_failure,
                    request=request,
                    profile=profile,
                    payload=payload,
                    base_url=self.base_url,
                    endpoint=self.chat_endpoint,
                    started=started,
                    batch_size=batch_size,
                    cancel_event=cancel_event,
                )
            data = self._post_json(self.chat_endpoint, payload)
            text = extract_openai_chat_text(data)
            result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
            result["usage"].update(_usage_from_response(data))
            result["transport"] = {
                "base_url": self.base_url,
                "endpoint": self.chat_endpoint,
                "duration_s": round(time.time() - started, 6),
                "coalesced_chat_parallel": True,
                "coalesced_batch_size": batch_size,
                "batch_size": batch_size,
            }
            return result
        except Exception as exc:
            return self._transport_failure(request, profile, started, str(exc), endpoint=self.chat_endpoint, coalesced_batch_size=batch_size)

    def _chat_batch_plan(self, requests: list[InferenceRequest], profile: ModelProfile) -> tuple[list[list[InferenceRequest]], list[tuple[list[InferenceRequest], dict[str, Any]]], int, int] | None:
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
        return chunks, payloads, max_cohort, _completion_chunk_concurrency(profile)

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
        planned = plan_compatible_payload_groups(
            request_list,
            payload_for_chunk=lambda chunk: _coalesced_completion_payload(chunk, profile, self.default_extra_body),
            chunk_items=lambda group: _completion_cohort_chunks(group, max_cohort=max_cohort, token_budget=token_budget),
            minimum=minimum,
        )
        if planned is None:
            return None
        chunks, payloads = planned
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
        auto_kv_suppressed = bool(payload.pop(AUTO_KV_BATCH_SUPPRESSED_KEY, False))
        try:
            prefetch_info = _maybe_prestage_common_kv_prefix(self, payload, chunk)
            data = self._post_json(self.completion_endpoint, payload)
            out = _coalesced_completion_results(chunk, profile, data, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, prefetch_info=prefetch_info, auto_kv_suppressed=auto_kv_suppressed)
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
        minimum = 1 if cancel_event is not None and _env_bool("DS4_PIPELINE_INTERNAL_STREAM_CANCELABLE_SINGLETONS", True) else max(2, int(os.environ.get("DS4_PIPELINE_COMPLETION_COHORT_MIN", "2") or "2"))
        if len(request_list) < minimum:
            return None
        max_cohort = _completion_effective_max_cohort(profile)
        token_budget = coalesced_completion_token_budget()
        planned = plan_compatible_payload_groups(
            request_list,
            payload_for_chunk=lambda chunk: _coalesced_completion_payload(chunk, profile, self.default_extra_body),
            chunk_items=lambda group: _completion_cohort_chunks(group, max_cohort=max_cohort, token_budget=token_budget),
            minimum=minimum,
        )
        if planned is None:
            return None
        chunks, payloads = planned
        for _, payload in payloads:
            payload["stream"] = True
        out: dict[str, dict] = {}
        concurrency = _completion_chunk_concurrency(profile)
        if concurrency > 1 and len(payloads) > 1:
            with ThreadPoolExecutor(max_workers=min(concurrency, len(payloads))) as executor:
                futures = [
                    executor.submit(self._run_completion_stream_chunk, chunk, profile, payload, on_result=on_result, on_delta=on_delta, cancel_event=cancel_event, original_batch_size=len(chunk))
                    for chunk, payload in payloads
                ]
                for future in as_completed(futures):
                    out.update(future.result())
        else:
            for chunk, payload in payloads:
                out.update(self._run_completion_stream_chunk(chunk, profile, payload, on_result=on_result, on_delta=on_delta, cancel_event=cancel_event, original_batch_size=len(chunk)))
        if len(chunks) > 1:
            _mark_coalesced_planned_split(out, original_batch_size=len(request_list), chunk_count=len(chunks), max_cohort=max_cohort, concurrency=concurrency)
        return out

    def _run_completion_stream_chunk(self, chunk: list[InferenceRequest], profile: ModelProfile, payload: dict[str, Any], *, on_result: Callable[[str, dict[str, Any]], None], on_delta: Callable[[str, str, dict[str, Any]], None] | None = None, cancel_event: Event | None = None, original_batch_size: int | None = None) -> dict[str, dict]:
        started = time.time()
        original_size = len(chunk) if original_batch_size is None else original_batch_size
        auto_kv_suppressed = bool(payload.pop(AUTO_KV_BATCH_SUPPRESSED_KEY, False))
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
                    previous_text = text_by_index[index]
                    next_text = previous_text + delta
                    stop_text = _answer_marker_early_stop_text(next_text) if _request_stop_on_answer_marker(chunk[index]) else None
                    text_by_index[index] = stop_text if stop_text is not None else next_text
                    if delta and on_delta is not None:
                        published_delta = delta
                        if stop_text is not None:
                            published_delta = stop_text[len(previous_text):] if stop_text.startswith(previous_text) else ""
                        if published_delta:
                            on_delta(chunk[index].request_id, published_delta, {"coalesced_batch_size": len(chunk), "choice_index": index})
                    if stop_text is not None:
                        result = _coalesced_stream_result(chunk[index], profile, stop_text, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=len(chunk), prefetch_info=_copy_optional_dict(prefetch_info), auto_kv_suppressed=auto_kv_suppressed, answer_marker_early_stop=True)
                        out[chunk[index].request_id] = result
                        completed_indexes.add(index)
                        on_result(chunk[index].request_id, result)
                        continue
                    if choice.get("finish_reason") is None:
                        continue
                    result = _coalesced_stream_result(chunk[index], profile, text_by_index[index], base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=len(chunk), prefetch_info=_copy_optional_dict(prefetch_info), auto_kv_suppressed=auto_kv_suppressed)
                    out[chunk[index].request_id] = result
                    completed_indexes.add(index)
                    on_result(chunk[index].request_id, result)
                if len(completed_indexes) >= len(chunk):
                    break
                if stream_deadline > 0 and time.time() >= stream_deadline and len(completed_indexes) < len(chunk):
                    timeout_error = f"coalesced completion stream wall timeout after {stream_timeout_s:.3f}s"
                    break
                if cancel_event is not None and cancel_event.is_set() and len(completed_indexes) < len(chunk):
                    timeout_error = "coalesced completion stream cancelled"
                    break
        except Exception as exc:
            if len(chunk) > 1 and _env_bool("DS4_PIPELINE_COMPLETION_BISECT_ON_FAILURE", True) and coalesced_failure_should_bisect(str(exc)):
                midpoint = max(1, len(chunk) // 2)
                out = {}
                for subchunk in (chunk[:midpoint], chunk[midpoint:]):
                    subpayload = _coalesced_completion_payload(subchunk, profile, self.default_extra_body)
                    if subpayload is None:
                        break
                    subpayload["stream"] = True
                    out.update(self._run_completion_stream_chunk(subchunk, profile, subpayload, on_result=on_result, on_delta=on_delta, cancel_event=cancel_event, original_batch_size=original_size))
                if len(out) == len(chunk):
                    return out
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
                result = _coalesced_stream_result(item, profile, text, base_url=self.base_url, endpoint=self.completion_endpoint, started=started, batch_size=len(chunk), prefetch_info=_copy_optional_dict(prefetch_info), auto_kv_suppressed=auto_kv_suppressed) if text else _coalesced_failure(item, profile, self.base_url, self.completion_endpoint, started, len(chunk), "stream ended before this coalesced completion finished")
            out[item.request_id] = result
            completed_indexes.add(index)
            on_result(item.request_id, result)
        if original_size != len(chunk):
            mark_coalesced_split(out, original_batch_size=original_size)
        return out

    def _transport_failure(self, request: InferenceRequest, profile: ModelProfile, started: float, error: str, *, endpoint: str | None = None, coalesced_batch_size: int | None = None) -> dict:
        result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=json.dumps({"error": error}, sort_keys=True), status="transport_failed")
        result["transport"] = {"base_url": self.base_url, "duration_s": round(time.time() - started, 6), "error": error}
        if endpoint is not None:
            result["transport"]["endpoint"] = endpoint
        if coalesced_batch_size is not None:
            result["transport"]["coalesced_batch_size"] = coalesced_batch_size
        return result

    def _post_json(self, endpoint: str, payload: dict[str, Any], *, extra_headers: dict[str, str] | None = None, timeout_s: float | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        headers.update(extra_headers or {})
        req = urlrequest.Request(self.base_url + endpoint, data=body, headers=headers, method="POST")
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_s if timeout_s is None else max(0.05, float(timeout_s))) as response:
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
            poll_timeout = 0.0
            idle_timeout_s = _sse_idle_timeout_s()
            first_event_timeout_s = _sse_first_event_timeout_s()
            if cancel_event is not None or idle_timeout_s > 0 or first_event_timeout_s > 0:
                poll_timeout = _env_float("DS4_PIPELINE_SSE_CANCEL_POLL_TIMEOUT_S", 1.0)
            event_data: list[str] = []
            saw_event = False
            stream_started_at = time.time()
            last_progress_at = stream_started_at
            while True:
                if cancel_event is not None and cancel_event.is_set(): break
                try:
                    if poll_timeout > 0:
                        try:
                            readable, _, _ = select.select([response.fileno()], [], [], max(0.05, float(poll_timeout)))
                        except (AttributeError, OSError, ValueError):
                            readable = [response]
                        if not readable:
                            now = time.time()
                            if not saw_event and first_event_timeout_s > 0 and (now - stream_started_at) >= first_event_timeout_s:
                                raise RuntimeError(f"SSE stream first event timeout after {first_event_timeout_s:.3f}s")
                            if saw_event and idle_timeout_s > 0 and (now - last_progress_at) >= idle_timeout_s:
                                raise RuntimeError(f"SSE stream idle timeout after {idle_timeout_s:.3f}s")
                            continue
                    raw_line = response.readline()
                except (TimeoutError, socket.timeout, OSError) as exc:
                    if cancel_event is not None and cancel_event.is_set(): break
                    raise RuntimeError(f"SSE stream read failed: {exc}") from exc
                if not raw_line: break
                last_progress_at = time.time()
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line == "":
                    if not event_data:
                        continue
                    text = "\n".join(event_data).strip()
                    event_data = []
                    if text == "[DONE]":
                        break
                    if text:
                        saw_event = True
                        yield json.loads(text)
                    continue
                if line.startswith("data:"): event_data.append(line[5:].strip())
            if cancel_event is not None and cancel_event.is_set(): return
            if event_data:
                text = "\n".join(event_data).strip()
                if text and text != "[DONE]":
                    saw_event = True
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
            coalesced_chat = runner.run_many_chat_incremental(request_list, profile, on_result=on_result, cancel_event=cancel_event)
            if coalesced_chat is not None:
                return coalesced_chat
        if _env_bool("DS4_PIPELINE_COHORT_COMPLETIONS", True):
            internal_stream = client_stream or _internal_stream_nonclient_cohort(request_list, cancel_event=cancel_event)
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
    auto_kv_suppressed = False
    for item in requests:
        if item.chat:
            return None
        payload = _openai_payload(item, profile)
        _merge_extra_body(payload, default_extra_body)
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            return None
        payload, stripped_auto_kv = maybe_suppress_generated_auto_kv_for_cohort(payload)
        comparable = dict(payload)
        comparable.pop("prompt", None)
        if shared is None:
            shared = comparable
        elif comparable != shared:
            return None
        prompts.append(prompt)
        auto_kv_suppressed = auto_kv_suppressed or stripped_auto_kv
    if shared is None:
        return None
    payload = dict(shared)
    payload["prompt"] = prompts
    if auto_kv_suppressed:
        payload[AUTO_KV_BATCH_SUPPRESSED_KEY] = True
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

def _coalesced_chat_completion_payload(requests: list[InferenceRequest], profile: ModelProfile, default_extra_body: dict[str, Any]) -> dict[str, Any] | None:
    prompts: list[str] = []
    shared: dict[str, Any] | None = None
    for item in requests:
        if not item.chat:
            return None
        if item.input.get("tools") is not None or item.input.get("tool_choice") is not None:
            return None
        prompt = _chat_completion_prompt(item, profile)
        if not prompt:
            return None
        payload = _openai_completion_prompt_payload(item, profile, prompt=prompt)
        _merge_extra_body(payload, default_extra_body)
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

def _maybe_prestage_common_kv_prefix(runner: OpenAICompatibleRunner, payload: dict[str, Any], requests: list[InferenceRequest]) -> dict[str, Any] | None:
    if not _env_bool("DS4_PIPELINE_PRESTAGE_COMMON_KV_PREFIX", True):
        return None
    strict_kv = _payload_has_strict_kv_load(payload)
    auto_kv = _payload_has_prestageable_auto_kv(payload)
    if not strict_kv and not auto_kv:
        return None
    circuit = getattr(runner, "jit_kv_circuit", None)
    if circuit is not None and not circuit.allow_prefetch():
        if strict_kv:
            disable_strict_kv(payload)
        return {
            "strategy": "jit-kv-circuit-open-cold-dispatch" if strict_kv else "jit-kv-circuit-open-prefetch-skipped",
            "cold_dispatch": True,
        }
    prefix = _common_prompt_prefix(requests)
    min_chars = _env_int("DS4_PIPELINE_PRESTAGE_COMMON_PREFIX_MIN_CHARS", 1024)
    if prefix is None or len(prefix) < max(1, min_chars):
        return None
    max_tokens = max(1, _env_int("DS4_PIPELINE_PRESTAGE_MAX_TOKENS", 1))
    prefetch_payload = build_prefetch_payload(payload, prefix=prefix, max_tokens=max_tokens)
    return run_prefetch(
        runner=runner,
        payload=payload,
        prefetch_payload=prefetch_payload,
        prefix_len=len(prefix),
        max_tokens=max_tokens,
        started=time.time(),
        circuit=circuit,
        fail_open=auto_kv and not strict_kv,
        disable_kv_on_cold=strict_kv,
    )


def _payload_ds4_kv_cache_plan(payload: dict[str, Any]) -> dict[str, Any] | None:
    extra = payload.get("extra_body")
    if not isinstance(extra, dict):
        return None
    plan = extra.get("ds4_kv_cache")
    return plan if isinstance(plan, dict) else None


def _payload_has_strict_kv_load(payload: dict[str, Any]) -> bool:
    plan = _payload_ds4_kv_cache_plan(payload)
    if plan is None:
        return False
    load = plan.get("load")
    if not isinstance(load, dict):
        return False
    if str(load.get("mode") or "skip") not in {"prefer", "require"}:
        return False
    miss_policy = str(plan.get("miss_policy") or "")
    return str(load.get("mode") or "") == "require" or miss_policy == "fail"


def _payload_has_prestageable_auto_kv(payload: dict[str, Any]) -> bool:
    if not _env_bool("DS4_PIPELINE_PRESTAGE_AUTO_KV_PREFIX", False):
        return False
    plan = _payload_ds4_kv_cache_plan(payload)
    if plan is None:
        return False
    cache_id = plan.get("cache_id")
    load = plan.get("load")
    store = plan.get("store")
    if not isinstance(cache_id, str) or not cache_id.startswith("ds4-auto:"):
        return False
    if not isinstance(load, dict) or str(load.get("mode") or "") != "prefer":
        return False
    if not isinstance(store, dict) or str(store.get("mode") or "") != "write_back":
        return False
    return str(plan.get("miss_policy") or "") == "compute_and_store"


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


def _cancelable_cohort_minimum(env_name: str, *, cancel_event: Event | None) -> int:
    if cancel_event is not None and _env_bool("DS4_PIPELINE_INTERNAL_STREAM_CANCELABLE_SINGLETONS", True):
        return 1
    return max(2, int(os.environ.get(env_name, "2") or "2"))


def _completion_chunk_concurrency(profile: ModelProfile) -> int:
    if not _profile_uses_pipeline(profile):
        return 1
    return max(1, _env_int("DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY", 4))


def _completion_stream_wall_timeout_s() -> float:
    return max(0.0, _env_float("DS4_PIPELINE_COMPLETION_STREAM_WALL_TIMEOUT_S", 0.0))


def _sse_idle_timeout_s() -> float:
    return max(0.0, _env_float("DS4_PIPELINE_SSE_IDLE_TIMEOUT_S", 0.0))


def _sse_first_event_timeout_s() -> float:
    return max(0.0, _env_float("DS4_PIPELINE_SSE_FIRST_EVENT_TIMEOUT_S", 0.0))


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

def _mark_chat_as_completion(out: dict[str, dict]) -> None:
    for result in out.values():
        transport: dict[str, Any] = result.setdefault("transport", {})
        transport["chat_as_completion_prompts"] = True
        transport["coalesced_chat_as_completion"] = True


def _chat_cohort_transport(profile: ModelProfile) -> str:
    value = profile.routing.get("chat_cohort_transport")
    return str(value) if value is not None else "batch_endpoint"


def _parallel_chat_concurrency(profile: ModelProfile, chunk_size: int, max_cohort: int) -> int:
    raw = profile.routing.get("parallel_chat_concurrency")
    if raw is None:
        raw = os.environ.get("DS4_PIPELINE_CHAT_PARALLEL_CONCURRENCY")
    try:
        value = int(raw) if raw is not None else int(max_cohort)
    except (TypeError, ValueError):
        value = int(max_cohort)
    return max(1, min(int(chunk_size), value))


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
    auto_kv_suppressed: bool = False,
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
        if auto_kv_suppressed:
            result["transport"]["coalesced_auto_kv_suppressed"] = True
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
    auto_kv_suppressed: bool = False,
    answer_marker_early_stop: bool = False,
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
    if auto_kv_suppressed:
        result["transport"]["coalesced_auto_kv_suppressed"] = True
    if answer_marker_early_stop:
        result["transport"]["answer_marker_early_stop"] = True
    return result


def _parallel_completion_prompt_stream_result(
    request: InferenceRequest,
    profile: ModelProfile,
    text: str,
    *,
    base_url: str,
    endpoint: str,
    started: float,
    batch_size: int,
    early_stop: bool,
) -> dict[str, Any]:
    result = make_result(request=request, profile_id=profile.profile_id, model_id=profile.model_id, backend=profile.backend, text=text)
    result["usage"].update({"completion_tokens": _estimate_text_tokens(text), "completion_tokens_estimated": True})
    result["transport"] = {
        "base_url": base_url,
        "endpoint": endpoint,
        "duration_s": round(time.time() - started, 6),
        "chat_as_completion_prompts": True,
        "coalesced_chat_parallel_completion": True,
        "parallel_completion_prompt_streaming": True,
        "coalesced_batch_size": batch_size,
        "batch_size": batch_size,
    }
    if early_stop:
        result["transport"]["answer_marker_early_stop"] = True
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


def _request_stop_on_answer_marker(request: InferenceRequest) -> bool:
    contract = request.output_contract if isinstance(request.output_contract, dict) else {}
    if bool(contract.get("stop_on_answer_marker")):
        return True
    if bool(request.input.get("stop_on_answer_marker")):
        return True
    metadata = request.input.get("metadata") if isinstance(request.input.get("metadata"), dict) else {}
    ds4_eval = metadata.get("ds4_eval") if isinstance(metadata.get("ds4_eval"), dict) else {}
    return bool(ds4_eval.get("stop_on_answer_marker"))


def _parallel_completion_prompt_streaming(request: InferenceRequest) -> bool:
    if not _request_stop_on_answer_marker(request):
        return False
    return _env_bool("DS4_PIPELINE_PARALLEL_COMPLETION_PROMPT_STREAMING", True)


def _answer_marker_early_stop_text(text: str) -> str | None:
    visible_start = text.find("</think>")
    visible_start = (visible_start + len("</think>")) if visible_start >= 0 else 0
    visible = text[visible_start:]
    for match in re.finditer(r"(?im)^[ \t]*(?:final[ \t]+)?answer[ \t]*:[ \t]*([^\r\n]*)", visible):
        value = match.group(1).strip()
        if not value or value.startswith("<") or not re.search(r"[A-Za-z0-9]", value):
            continue
        rest = visible[match.end():]
        newline = re.search(r"[\r\n]", rest)
        if newline is not None:
            return text[:visible_start + match.end() + newline.start()].rstrip()
        if len(rest) >= _answer_marker_stop_tail_chars():
            return text[:visible_start + match.end()].rstrip()
    return None


def _answer_marker_stop_tail_chars() -> int:
    try:
        return max(0, int(os.environ.get("DS4_PIPELINE_ANSWER_MARKER_STOP_TAIL_CHARS", "8") or "8"))
    except ValueError:
        return 8


def _internal_stream_nonclient_cohort(requests: list[InferenceRequest], *, cancel_event: Event | None = None) -> bool:
    raw = os.environ.get("DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS")
    if raw is not None:
        return _env_bool("DS4_PIPELINE_INTERNAL_STREAM_ALL_COHORTS", True)
    if cancel_event is not None and _env_bool("DS4_PIPELINE_INTERNAL_STREAM_CANCELABLE_COHORTS", True):
        return True
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
    _apply_openai_payload_extras(payload, request, profile)
    return payload


def _openai_completion_prompt_payload(request: InferenceRequest, profile: ModelProfile, *, prompt: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": _served_model_id(profile),
        "prompt": prompt,
        "temperature": request.temperature,
        "max_tokens": max(1, int(request.max_output_tokens) + int(request.thinking_budget_tokens)),
    }
    _apply_openai_payload_extras(payload, request, profile)
    return payload


def _apply_openai_payload_extras(payload: dict[str, Any], request: InferenceRequest, profile: ModelProfile) -> None:
    _merge_openai_request_fields(payload, request)
    sampling = openai_sampling_controls(request.input)
    if sampling:
        payload.update(sampling)
    merge_request_extra_body(payload, request, profile)
    extra_body = kv_cache_extra_body(request.input)
    if not extra_body:
        auto_plan = _auto_kv_cache_plan(payload, request, profile)
        if auto_plan is not None:
            extra_body = {"ds4_kv_cache": auto_plan}
    if extra_body:
        payload.update(kv_cache_vllm_request_fields({"kv_cache_plan": extra_body["ds4_kv_cache"]}))
        payload["extra_body"] = {**dict(payload.get("extra_body") or {}), **extra_body}


def _chat_completion_prompt(request: InferenceRequest, profile: ModelProfile) -> str:
    data = request.input
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    for container in (data, metadata):
        for key in ("rendered_prompt", "prompt"):
            value = container.get(key) if isinstance(container, dict) else None
            if isinstance(value, str) and value:
                return value
    if data.get("messages") is not None:
        return rendered_chat_prompt_from_input(profile, data, thinking_budget_tokens=request.thinking_budget_tokens)
    return request_prompt(request)


def openai_sampling_controls(input_payload: dict[str, Any]) -> dict[str, Any]:
    value = input_payload.get("openai_sampling")
    return dict(value) if isinstance(value, dict) else {}


def _auto_kv_cache_plan(payload: dict[str, Any], request: InferenceRequest, profile: ModelProfile) -> dict[str, Any] | None:
    if not _env_bool("DS4_PIPELINE_AUTO_KV_CACHE", False):
        return None
    if request.input.get("disable_auto_kv_cache") is True:
        return None
    if request.input.get("kv_cache") is not None or request.input.get("kv_cache_plan") is not None:
        return None
    if "kv_transfer_params" in payload:
        return None
    service_id = _profile_service_id(profile)
    allowed_services = _env_csv_set("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
    if allowed_services and (service_id or profile.profile_id) not in allowed_services:
        return None
    material = _auto_kv_cache_material(payload, request, profile, service_id=service_id)
    digest = hashlib.sha256(_json_dumps_canonical(material).encode("utf-8")).hexdigest()
    cache_scope = service_id or profile.profile_id
    cache_id = f"ds4-auto:{cache_scope}:{digest[:32]}"
    plan = {
        "format": "ds4-kv-cache-plan-v1",
        "backend": _auto_kv_backend(service_id),
        "cache_id": cache_id,
        "prefix_hash": "sha256:" + digest,
        "load": {"mode": "prefer", "transport": "local_store", "cache_key": cache_id},
        "store": {"mode": "write_back", "transport": "local_store", "cache_key": cache_id, "on_error": "warn"},
        "miss_policy": "compute_and_store",
        "route_affinity": "preferred",
        "model_fingerprint": {
            "model_id": str(payload.get("model") or profile.model_id),
            "profile_id": profile.profile_id,
            "runtime_contract_id": profile.runtime_contract_id,
            "service_id": service_id,
        },
        "operation": "load_store",
    }
    plan["batch_key_hash"] = "sha256:" + hashlib.sha256(_json_dumps_canonical(_auto_kv_batch_key_material(plan)).encode("utf-8")).hexdigest()
    return plan


def _auto_kv_cache_material(payload: dict[str, Any], request: InferenceRequest, profile: ModelProfile, *, service_id: str | None) -> dict[str, Any]:
    return {
        "format": "ds4-auto-kv-cache-key-v1",
        "chat": bool(request.chat),
        "messages": payload.get("messages"),
        "prompt": payload.get("prompt"),
        "model": payload.get("model"),
        "profile_id": profile.profile_id,
        "runtime_contract_id": profile.runtime_contract_id,
        "service_id": service_id,
        "thinking_budget_tokens": request.thinking_budget_tokens,
        "extra_body": dict(payload.get("extra_body") or {}),
    }


def _auto_kv_batch_key_material(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "backend": plan["backend"],
        "cache_id": plan["cache_id"],
        "prefix_hash": plan["prefix_hash"],
        "load": plan["load"],
        "store": plan["store"],
        "miss_policy": plan["miss_policy"],
        "route_affinity": plan["route_affinity"],
        "model_fingerprint": plan["model_fingerprint"],
    }


def _profile_service_id(profile: ModelProfile) -> str | None:
    pipeline = profile.routing.get("pipeline")
    if isinstance(pipeline, dict) and pipeline.get("service_id"):
        return str(pipeline["service_id"])
    value = profile.routing.get("pipeline_service_id") or profile.routing.get("service_id")
    return str(value) if value else None


def _auto_kv_backend(service_id: str | None) -> str:
    if service_id == "dsv4_flash_pp8":
        return "dsv4_hma"
    if service_id and service_id.startswith(("qwen", "gemma", "kimi")):
        return "lmcache"
    return "auto"


def _json_dumps_canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _env_csv_set(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    return {item.strip() for item in raw.split(",") if item.strip()}


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
