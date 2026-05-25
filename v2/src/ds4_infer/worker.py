from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import socket
from typing import Any, Callable

from .profiles import ProfileRegistry
from .queue import CPU_QUEUE_TIMEOUT_KEY, QUEUE_FORMAT, InferenceQueue, QueueClaim
from .runners import Runner

_CPU_SERVICE: Any | None = None
FinishHook = Callable[[QueueClaim, dict[str, Any]], None]


class BatchWorker:
    def __init__(
        self,
        *,
        queue: InferenceQueue,
        registry: ProfileRegistry,
        runner: Runner,
        worker_id: str | None = None,
        lease_ttl_s: int = 900,
        heartbeat_interval_s: float = 5.0,
        cpu_service: Any | None = None,
    ) -> None:
        self.queue = queue
        self.registry = registry
        self.runner = runner
        self.worker_id = worker_id or f"{socket.gethostname()}:{id(self)}"
        self.lease_ttl_s = lease_ttl_s
        self.heartbeat_interval_s = heartbeat_interval_s
        self.cpu_service = cpu_service

    def run_once(
        self,
        *,
        node_id: str | None = None,
        batch_id: str | None = None,
        batch_key: str | None = None,
        limit: int = 1,
        concurrency: int = 1,
        on_result: Callable[[QueueClaim, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be positive")
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        reap = self.queue.requeue_expired_leases()
        groups: dict[str, dict[str, int]] = {}
        claimed = completed = failed = lost = heartbeats = 0
        active_batch_key = batch_key

        def claim_more(wanted: int) -> list[QueueClaim]:
            nonlocal active_batch_key, claimed
            if wanted < 1 or claimed >= limit:
                return []
            claims = self.queue.claim_requests(node_id=node_id, batch_id=batch_id, batch_key=active_batch_key, limit=min(wanted, (limit - claimed)), leased_by=self.worker_id, lease_ttl_s=self.lease_ttl_s)
            if claims and active_batch_key is None:
                active_batch_key = claims[0].batch_key
            _record_claims(groups, claims)
            claimed += len(claims)
            return claims

        initial_claims = claim_more(concurrency)
        if not initial_claims:
            return _summary(0, 0, 0, 0, groups, reap)
        if initial_claims[0].request_kind == "cpu" and claimed < limit:
            initial_claims.extend(claim_more(limit - claimed))
        if _claims_use_batch_runner(self.runner, initial_claims):
            payload = self._run_claim_batch(initial_claims, concurrency=concurrency, groups=groups, reap=reap, on_result=on_result)
            return payload
        stream = self._run_streaming_claims(initial_claims, claim_more=claim_more, concurrency=concurrency, groups=groups, on_result=on_result)
        completed += stream["completed_count"]
        failed += stream["failed_count"]
        lost += stream["lost_lease_count"]
        heartbeats += stream["heartbeat_count"]
        payload = _summary(claimed, completed, failed, lost, groups, reap)
        payload["heartbeat_count"] = heartbeats
        return payload

    def _run_streaming_claims(self, initial_claims: list[QueueClaim], *, claim_more: Callable[[int], list[QueueClaim]], concurrency: int, groups: dict[str, dict[str, int]], on_result: FinishHook | None) -> dict[str, int]:
        completed = failed = lost = heartbeats = 0
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(self._run_claim, claim): claim for claim in initial_claims}
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=self.heartbeat_interval_s, return_when=FIRST_COMPLETED)
                if not done:
                    heartbeats += self.queue.heartbeat(lease_ids=(futures[future].lease_id for future in pending), lease_ttl_s=self.lease_ttl_s)
                    continue
                for future in done:
                    claim = futures.pop(future)
                    state = self._finish_claim_result(claim, _future_result(future, claim), groups, on_result)
                    completed += 1 if state == "completed" else 0
                    failed += 1 if state == "failed" else 0
                    lost += 1 if state == "lost" else 0
                for claim in claim_more(concurrency - len(pending)):
                    future = pool.submit(self._run_claim, claim)
                    futures[future] = claim
                    pending.add(future)
        return {"completed_count": completed, "failed_count": failed, "lost_lease_count": lost, "heartbeat_count": heartbeats}

    def _run_claim(self, claim: QueueClaim) -> dict[str, Any]:
        if claim.request_kind != "model" or claim.request is None:
            return _failure(claim, "worker cannot run CPU claim without batch path")
        profile = self.registry.get(claim.selected_profile_id)
        if hasattr(self.runner, "run_one_on_node"):
            result = self.runner.run_one_on_node(claim.request, profile, claim.selected_node_id)  # type: ignore[attr-defined]
        else:
            result = self.runner.run_one(claim.request, profile)
        if claim.selected_node_id:
            result["selected_node"] = {"node_id": claim.selected_node_id}
        result["batch_key"] = claim.batch_key
        return result

    def _run_claim_batch(self, claims: list[QueueClaim], *, concurrency: int, groups: dict[str, dict[str, int]], reap: dict[str, Any], on_result: Callable[[QueueClaim, dict[str, Any]], None] | None) -> dict[str, Any]:
        completed = failed = lost = heartbeats = 0
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._run_claims_as_batch, claims, concurrency)
            while True:
                done, _ = wait({future}, timeout=self.heartbeat_interval_s, return_when=FIRST_COMPLETED)
                if done:
                    break
                heartbeats += self.queue.heartbeat(lease_ids=(claim.lease_id for claim in claims), lease_ttl_s=self.lease_ttl_s)
            results = future.result()
        for claim, result in results:
            state = self._finish_claim_result(claim, result, groups, on_result)
            completed += 1 if state == "completed" else 0
            failed += 1 if state == "failed" else 0
            lost += 1 if state == "lost" else 0
        payload = _summary(len(claims), completed, failed, lost, groups, reap)
        payload["heartbeat_count"] = heartbeats
        payload["batch_dispatch_count"] = 1
        return payload

    def _finish_claim_result(self, claim: QueueClaim, result: dict[str, Any], groups: dict[str, dict[str, int]], on_result: FinishHook | None) -> str:
        state = "completed" if result.get("status") == "completed" else "failed"
        error = None if state == "completed" else str(result.get("status", "failed"))
        accepted = self.queue.finish_request(request_id=claim.request_id, lease_id=claim.lease_id, state=state, result=result, error=error)
        if not accepted:
            return "lost"
        groups[claim.batch_key]["completed_count" if state == "completed" else "failed_count"] += 1
        if on_result is not None:
            on_result(claim, result)
        return state

    def _run_claims_as_batch(self, claims: list[QueueClaim], concurrency: int) -> list[tuple[QueueClaim, dict[str, Any]]]:
        if claims[0].request_kind == "cpu":
            return self._run_cpu_claims(claims, concurrency)
        profile = self.registry.get(claims[0].selected_profile_id)
        requests = [claim.request for claim in claims if claim.request is not None]
        if len(requests) != len(claims):
            return [(claim, _failure(claim, "missing model request payload")) for claim in claims]
        results = self.runner.run_many_on_node(requests, profile, claims[0].selected_node_id, concurrency=concurrency)  # type: ignore[attr-defined]
        out: list[tuple[QueueClaim, dict[str, Any]]] = []
        for claim in claims:
            result = results.get(claim.request_id) or _failure(claim, "batch runner omitted request result")
            if claim.selected_node_id:
                result["selected_node"] = {"node_id": claim.selected_node_id}
            result["batch_key"] = claim.batch_key
            out.append((claim, result))
        return out

    def _run_cpu_claims(self, claims: list[QueueClaim], concurrency: int) -> list[tuple[QueueClaim, dict[str, Any]]]:
        service = claims[0].service_name or ""
        if self.cpu_service is None:
            self.cpu_service = _default_cpu_service()
        items, timeout_s = _cpu_items_and_timeout(claims, self.lease_ttl_s)
        payload = {"service": service, "items": items, "concurrency": concurrency, "timeout_s": timeout_s}
        try:
            batch = self.cpu_service.run_batch(payload)
            rows = batch.get("results", []) if isinstance(batch, dict) else []
        except Exception as exc:
            rows = [{"ok": False, "error": str(exc)} for _ in claims]
        out: list[tuple[QueueClaim, dict[str, Any]]] = []
        for index, claim in enumerate(claims):
            row = rows[index] if index < len(rows) and isinstance(rows[index], dict) else {"ok": False, "error": "CPU batch omitted result"}
            status = "completed" if row.get("ok") else "failed"
            out.append((claim, {"format": "ds4-cpu-service-result-v1", "request_id": claim.request_id, "status": status, "service": service, "output": row, "batch_key": claim.batch_key}))
        return out


def _record_claims(groups: dict[str, dict[str, int]], claims: list[QueueClaim]) -> None:
    for claim in claims:
        group = groups.setdefault(claim.batch_key, {"claimed_count": 0, "completed_count": 0, "failed_count": 0})
        group["claimed_count"] += 1


def _claims_use_batch_runner(runner: Runner, claims: list[QueueClaim]) -> bool:
    return bool(claims and claims[0].request_kind == "cpu")


def _cpu_items_and_timeout(claims: list[QueueClaim], default_timeout_s: int) -> tuple[list[dict[str, Any]], float]:
    items: list[dict[str, Any]] = []
    timeouts: list[float] = []
    for claim in claims:
        item = dict(claim.payload or {})
        timeout = item.pop(CPU_QUEUE_TIMEOUT_KEY, None)
        if timeout is not None:
            timeouts.append(float(timeout))
        items.append(item)
    return items, max(timeouts) if timeouts else float(default_timeout_s)


def _default_cpu_service() -> Any:
    global _CPU_SERVICE
    if _CPU_SERVICE is None:
        from ds4_tools.cpu_batch import CpuBatchService
        _CPU_SERVICE = CpuBatchService()
    return _CPU_SERVICE


def _future_result(future: Any, claim: QueueClaim) -> dict[str, Any]:
    try:
        return future.result()
    except Exception as exc:
        return {
            "format": "ds4-inference-failure-v1",
            "request_id": claim.request_id,
            "status": "runner_exception",
            "error": str(exc),
            "batch_key": claim.batch_key,
        }


def _failure(claim: QueueClaim, error: str) -> dict[str, Any]:
    return {
        "format": "ds4-inference-failure-v1",
        "request_id": claim.request_id,
        "status": "runner_exception",
        "error": error,
        "batch_key": claim.batch_key,
    }


def _summary(claimed: int, completed: int, failed: int, lost: int, groups: dict[str, dict[str, int]], reap: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": QUEUE_FORMAT,
        "claimed_count": claimed,
        "completed_count": completed,
        "failed_count": failed,
        "lost_lease_count": lost,
        "state": "worked" if claimed else "idle",
        "reaped": {"requeued_count": reap.get("requeued_count", 0), "failed_count": reap.get("failed_count", 0)},
        "groups": [dict({"batch_key": key}, **value) for key, value in sorted(groups.items())],
    }
