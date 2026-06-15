from __future__ import annotations

from collections import deque
import json
import os
import threading
import time
from typing import Any, Callable

from .env_utils import env_bool as _env_bool


class JitKvCircuitBreaker:
    def __init__(
        self,
        *,
        enabled: bool = True,
        window_s: float = 60.0,
        min_samples: int = 8,
        failure_ratio: float = 0.5,
        cooldown_s: float = 120.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.window_s = max(1.0, float(window_s))
        self.min_samples = max(1, int(min_samples))
        self.failure_ratio = min(1.0, max(0.0, float(failure_ratio)))
        self.cooldown_s = max(1.0, float(cooldown_s))
        self.time_fn = time_fn or time.time
        self.open_until = 0.0
        self._lock = threading.RLock()
        self._samples: deque[tuple[float, bool]] = deque()
        self.submitted_count = 0
        self.completed_count = 0
        self.failed_count = 0
        self.gate_released_count = 0
        self.last_error: str | None = None

    def allow_prefetch(self) -> bool:
        with self._lock:
            if not self.enabled:
                return True
            return self.time_fn() >= self.open_until

    def record_submission(self) -> None:
        with self._lock:
            self.submitted_count += 1

    def record_success(self) -> None:
        with self._lock:
            self.completed_count += 1
            self._record(True, None)

    def record_failure(self, error: str | None = None) -> None:
        with self._lock:
            self.failed_count += 1
            self._record(False, error)

    def record_gate_release(self, count: int) -> None:
        with self._lock:
            self.gate_released_count += max(0, int(count))

    def status(self) -> dict[str, Any]:
        with self._lock:
            self._prune()
            ratio = self._failure_ratio()
            now = self.time_fn()
            is_open = self.enabled and now < self.open_until
            return {
                "jit_kv_circuit_enabled": self.enabled,
                "jit_kv_circuit_open": is_open,
                "jit_kv_circuit_open_until": self.open_until if is_open else None,
                "jit_kv_circuit_failure_ratio": ratio,
                "jit_kv_circuit_samples": len(self._samples),
                "jit_kv_prefetch_submitted_count": self.submitted_count,
                "jit_kv_prefetch_completed_count": self.completed_count,
                "jit_kv_prefetch_failed_count": self.failed_count,
                "jit_kv_prefetch_gate_released_count": self.gate_released_count,
                "jit_kv_circuit_last_error": self.last_error,
            }

    def _record(self, success: bool, error: str | None) -> None:
        with self._lock:
            if not self.enabled:
                return
            now = self.time_fn()
            self._samples.append((now, bool(success)))
            if error:
                self.last_error = str(error)[-1000:]
            self._prune(now=now)
            if len(self._samples) < self.min_samples:
                return
            if self._failure_ratio() >= self.failure_ratio:
                self.open_until = max(self.open_until, now + self.cooldown_s)

    def _prune(self, *, now: float | None = None) -> None:
        with self._lock:
            now = self.time_fn() if now is None else now
            cutoff = now - self.window_s
            while self._samples and self._samples[0][0] < cutoff:
                self._samples.popleft()

    def _failure_ratio(self) -> float:
        with self._lock:
            if not self._samples:
                return 0.0
            failed = sum(1 for _ts, success in self._samples if not success)
            return failed / max(1, len(self._samples))


def build_prefetch_payload(payload: dict[str, Any], *, prefix: str, max_tokens: int) -> dict[str, Any]:
    prefetch_payload: dict[str, Any] = {"model": payload["model"], "prompt": prefix, "max_tokens": max_tokens, "temperature": payload.get("temperature", 0), "stream": False}
    extra_body = payload.get("extra_body")
    if isinstance(extra_body, dict):
        prefetch_payload["extra_body"] = dict(extra_body)
    return prefetch_payload


def run_prefetch(
    *,
    runner: Any,
    payload: dict[str, Any],
    prefetch_payload: dict[str, Any],
    prefix_len: int,
    max_tokens: int,
    started: float,
    circuit: Any | None,
    fail_open: bool = False,
    disable_kv_on_cold: bool = True,
) -> dict[str, Any]:
    try:
        if circuit is not None:
            circuit.record_submission()
        response = _post_prefetch(runner, prefetch_payload)
        if circuit is not None:
            circuit.record_success()
        return _prefetch_result(response, prefix_len=prefix_len, max_tokens=max_tokens, started=started)
    except Exception as exc:
        if circuit is not None:
            circuit.record_failure(str(exc))
        if fail_open or (circuit is not None and not circuit.allow_prefetch()):
            if disable_kv_on_cold:
                disable_strict_kv(payload)
            strategy = "jit-kv-prefetch-failed-auto-cold-dispatch" if fail_open else "jit-kv-prefetch-failed-cold-dispatch"
            return _cold_dispatch_result(exc, prefix_len=prefix_len, started=started, strategy=strategy)
        raise


def disable_strict_kv(payload: dict[str, Any]) -> None:
    payload.pop("kv_transfer_params", None)
    extra = payload.get("extra_body")
    if isinstance(extra, dict):
        extra.pop("ds4_kv_cache", None)
        if not extra:
            payload.pop("extra_body", None)


def _post_prefetch(runner: Any, payload: dict[str, Any]) -> dict[str, Any] | None:
    token = os.environ.get("DS4_API_JIT_KV_PREFETCH_TOKEN", "")
    use_endpoint = _env_bool("DS4_API_JIT_KV_PREFETCH_API", bool(token))
    timeout_s = _prefetch_timeout_s(runner)
    if not use_endpoint:
        runner._post_json(runner.completion_endpoint, payload, timeout_s=timeout_s)
        return None
    headers = {"x-ds4-kv-prefetch-token": token} if token else {}
    response = runner._post_json("/ds4/kv/prefetch", payload, extra_headers=headers, timeout_s=timeout_s)
    if str(response.get("status") or "") in {"failed", "error"}:
        raise RuntimeError(json.dumps(response, sort_keys=True)[-4000:])
    return response


def _prefetch_timeout_s(runner: Any) -> float:
    raw = os.environ.get("DS4_API_JIT_KV_PREFETCH_TIMEOUT_S", "")
    try:
        value = float(raw) if raw else 10.0
    except ValueError:
        value = 10.0
    runner_timeout = getattr(runner, "timeout_s", None)
    try:
        runner_timeout_f = float(runner_timeout)
    except (TypeError, ValueError):
        runner_timeout_f = value
    return max(0.05, min(value, runner_timeout_f))


def _prefetch_result(response: dict[str, Any] | None, *, prefix_len: int, max_tokens: int, started: float) -> dict[str, Any]:
    strategy = "ds4-kv-prefetch-endpoint" if response is not None else "single-prefix-load-before-cohort"
    out = {"common_prefix_chars": prefix_len, "duration_s": round(time.time() - started, 6), "max_tokens": max_tokens, "strategy": strategy}
    if isinstance(response, dict):
        out["prefetch_status"] = response.get("status")
        out["adoptable"] = bool(response.get("adoptable"))
        out["prefetch_ticket"] = response.get("prefetch_ticket")
    return out


def _cold_dispatch_result(exc: Exception, *, prefix_len: int, started: float, strategy: str = "jit-kv-prefetch-failed-cold-dispatch") -> dict[str, Any]:
    return {"common_prefix_chars": prefix_len, "duration_s": round(time.time() - started, 6), "strategy": strategy, "cold_dispatch": True, "error": str(exc)[-1000:]}
