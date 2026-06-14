from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from queue import Empty, Queue
import socket
from threading import Event
from typing import Any, Callable, Mapping

from .pipeline import PipelineProfile
from .profiles import ProfileRegistry
from .queue import CPU_QUEUE_TIMEOUT_KEY, QueueClaim
from .runners import Runner

FinishHook = Callable[[QueueClaim, dict[str, Any]], None]
_CPU_SERVICE: Any | None = None
_TERMINAL_STATES = {"completed", "failed", "cancelled"}


class BatchWorker:
    def __init__(self, *, queue: Any, registry: ProfileRegistry, runner: Runner, worker_id: str | None = None, lease_ttl_s: int = 900, heartbeat_interval_s: float = 5.0, transport_max_attempts: int = 3) -> None:
        self.queue = queue
        self.registry = registry
        self.runner = runner
        self.worker_id = worker_id or f"{socket.gethostname()}:{id(self)}"
        self.lease_ttl_s = lease_ttl_s
        self.heartbeat_interval_s = heartbeat_interval_s
        self.transport_max_attempts = transport_max_attempts

    def run_once(
        self,
        *,
        node_id: str | None = None,
        batch_id: str | None = None,
        limit: int = 1,
        concurrency: int = 1,
        node_profile_ids: tuple[str, ...] | None = None,
        max_node_depth: int = 0,
        batch_linger_s: float = 0.0,
        kv_capacity_bytes: int = 0,
        kv_shard_layouts_by_profile: Mapping[str, PipelineProfile] | None = None,
        batch_limits_by_service: Mapping[str, int] | None = None,
        refill_low_watermarks_by_service: Mapping[str, int] | None = None,
        on_result: FinishHook | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or concurrency < 1:
            raise ValueError("limit and concurrency must be positive")
        reap = self.queue.requeue_expired_leases()
        prefilled = self.queue.prepare_ready(
            node_id=node_id,
            eligible_profile_ids=node_profile_ids or (),
            batch_id=batch_id,
            limit=limit,
            leased_by=self.worker_id,
            lease_ttl_s=self.lease_ttl_s,
            max_node_depth=max_node_depth,
            kv_capacity_bytes=kv_capacity_bytes,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile or {},
        )
        claims = self.queue.claim_ready_batch(
            node_id=node_id,
            batch_id=batch_id,
            limit=min(limit, concurrency),
            leased_by=self.worker_id,
            lease_ttl_s=self.lease_ttl_s,
            batch_linger_s=batch_linger_s,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile or {},
            batch_limits_by_service=batch_limits_by_service or {},
        )
        if not claims:
            return _summary(0, 0, 0, reap, prefilled_count=prefilled, batch_dispatch_count=0)
        if claims[0].request_kind == "cpu":
            pairs = self._run_cpu_claims(claims, concurrency)
            mode = "cpu_batch"
        elif _can_batch_models(self.runner, claims):
            if _can_batch_models_incremental(self.runner, claims):
                completed, failed, retried = self._run_model_batch_incremental(claims, concurrency, on_result)
                return _summary(len(claims), completed, failed, reap, prefilled_count=prefilled, retried_count=retried, batch_dispatch_count=1, batch_dispatch_mode="batch_incremental")
            pairs = self._run_model_batch(claims, concurrency)
            mode = "batch"
        elif _service_refill_low_watermark(claims[0].selected_service_id, refill_low_watermarks_by_service or {}) > 0:
            completed, failed, retried, claimed, refill_prefilled = self._run_refill_stream(
                claims,
                concurrency,
                on_result,
                node_id=node_id,
                batch_id=batch_id,
                node_profile_ids=node_profile_ids or (),
                max_node_depth=max_node_depth,
                kv_capacity_bytes=kv_capacity_bytes,
                kv_shard_layouts_by_profile=kv_shard_layouts_by_profile or {},
                batch_limits_by_service=batch_limits_by_service or {},
                refill_low_watermark=_service_refill_low_watermark(claims[0].selected_service_id, refill_low_watermarks_by_service or {}),
            )
            return _summary(claimed, completed, failed, reap, prefilled_count=prefilled + refill_prefilled, retried_count=retried, batch_dispatch_count=claimed, batch_dispatch_mode="rolling_refill")
        else:
            completed, failed, retried = self._run_stream(claims, concurrency, on_result)
            return _summary(len(claims), completed, failed, reap, prefilled_count=prefilled, retried_count=retried, batch_dispatch_count=len(claims), batch_dispatch_mode="per_request")
        completed = failed = retried = 0
        for claim, result in pairs:
            item_completed, item_failed, item_retried = self._finish_pair(claim, result, on_result)
            completed += item_completed
            failed += item_failed
            retried += item_retried
        return _summary(len(claims), completed, failed, reap, prefilled_count=prefilled, retried_count=retried, batch_dispatch_count=1, batch_dispatch_mode=mode)

    def _finish_pair(self, claim: QueueClaim, result: dict[str, Any], on_result: FinishHook | None) -> tuple[int, int, int]:
        if result.get("status") == "transport_failed":
            retry_state = self.queue.retry_transport_failure(request_id=claim.request_id, lease_id=claim.lease_id, result=result, max_attempts=self.transport_max_attempts)
            if retry_state == "requeued":
                return (0, 0, 1)
            if retry_state in {"failed", "cancelled"} and on_result is not None:
                on_result(claim, result)
            return (0, 1, 0) if retry_state == "failed" else (0, 0, 0)
        result_status = str(result.get("status") or "")
        if result_status == "cancelled":
            state = "cancelled"
        else:
            state = "completed" if result_status == "completed" else "failed"
        if not self.queue.finish_request(request_id=claim.request_id, lease_id=claim.lease_id, state=state, result=result, error=None if state == "completed" else str(result.get("status", "failed"))):
            return (0, 0, 0)
        if on_result is not None:
            on_result(claim, result)
        if state == "completed":
            return (1, 0, 0)
        if state == "failed":
            return (0, 1, 0)
        return (0, 0, 0)

    def _run_model_batch(self, claims: list[QueueClaim], concurrency: int) -> list[tuple[QueueClaim, dict[str, Any]]]:
        profile = self.registry.get(claims[0].selected_profile_id)
        requests = [claim.request for claim in claims if claim.request is not None]
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.runner.run_many_on_node, requests, profile, claims[0].selected_node_id, concurrency=concurrency)  # type: ignore[attr-defined]
                results = self._await_with_heartbeat(future, claims)
        except Exception as exc:
            return [(claim, _failure(claim, str(exc))) for claim in claims]
        return [(claim, _result_for_claim(claim, results.get(claim.request_id))) for claim in claims]

    def _run_model_batch_incremental(self, claims: list[QueueClaim], concurrency: int, on_result: FinishHook | None, *, on_item_finished: Callable[[str], None] | None = None) -> tuple[int, int, int]:
        profile = self.registry.get(claims[0].selected_profile_id)
        requests = [claim.request for claim in claims if claim.request is not None]
        claim_by_id = {claim.request_id: claim for claim in claims}
        result_queue: Queue[tuple[str, dict[str, Any]]] = Queue()
        cancel_event = Event()
        finished: set[str] = set()
        completed = failed = retried = 0

        def push_result(request_id: str, result: dict[str, Any]) -> None:
            result_queue.put((request_id, result))

        def drain_results() -> None:
            nonlocal completed, failed, retried
            while True:
                try:
                    request_id, result = result_queue.get_nowait()
                except Empty:
                    return
                claim = claim_by_id.get(request_id)
                if claim is None or request_id in finished:
                    continue
                item_completed, item_failed, item_retried = self._finish_pair(claim, _result_for_claim(claim, result), on_result)
                completed += item_completed
                failed += item_failed
                retried += item_retried
                finished.add(request_id)
                _notify_item_finished(on_item_finished, request_id)

        pool = ThreadPoolExecutor(max_workers=1)
        wait_for_runner = True
        try:
            future = pool.submit(self.runner.run_many_on_node_incremental, requests, profile, claims[0].selected_node_id, concurrency=concurrency, on_result=push_result, on_delta=lambda request_id, text, payload: _push_stream_delta(self.queue, request_id, text, payload), cancel_event=cancel_event)  # type: ignore[attr-defined]
            while not future.done():
                wait([future], timeout=self.heartbeat_interval_s)
                drain_results()
                pending = [claim for claim in claims if claim.request_id not in finished]
                if pending and not future.done():
                    if self._cancel_requested(pending):
                        cancel_event.set()
                        item_completed, item_failed, item_retried = _finish_cancelled_or_terminal_pending(self, claims, finished, on_result, on_item_finished)
                        completed += item_completed
                        failed += item_failed
                        retried += item_retried
                        pending = [claim for claim in claims if claim.request_id not in finished]
                        if not pending:
                            wait_for_runner = False
                            return completed, failed, retried
                    if pending:
                        self._heartbeat(pending)
            drain_results()
            results = future.result()
        except Exception as exc:
            results = {claim.request_id: _failure(claim, str(exc)) for claim in claims if claim.request_id not in finished}
        finally:
            pool.shutdown(wait=wait_for_runner, cancel_futures=not wait_for_runner)
        for claim in claims:
            if claim.request_id in finished:
                continue
            item_completed, item_failed, item_retried = self._finish_pair(claim, _result_for_claim(claim, results.get(claim.request_id)), on_result)
            completed += item_completed
            failed += item_failed
            retried += item_retried
            finished.add(claim.request_id)
        return completed, failed, retried

    def run_resident_refill_stream(
        self,
        claims: list[QueueClaim],
        concurrency: int,
        on_result: FinishHook | None,
        *,
        node_id: str | None,
        node_profile_ids: tuple[str, ...],
        max_node_depth: int,
        kv_capacity_bytes: int,
        kv_shard_layouts_by_profile: Mapping[str, PipelineProfile],
        batch_limits_by_service: Mapping[str, int],
        refill_low_watermark: int,
        on_item_finished: Callable[[str], None] | None = None,
    ) -> tuple[int, int, int, int, int]:
        return self._run_refill_stream(
            claims,
            concurrency,
            on_result,
            node_id=node_id,
            batch_id=None,
            node_profile_ids=node_profile_ids,
            max_node_depth=max_node_depth,
            kv_capacity_bytes=kv_capacity_bytes,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
            batch_limits_by_service=batch_limits_by_service,
            refill_low_watermark=refill_low_watermark,
            share_compute_domain=True,
            on_item_finished=on_item_finished,
        )

    def _cancel_requested(self, claims: list[QueueClaim]) -> bool:
        for claim in claims:
            if bool(self.queue.status(request_id=claim.request_id, refresh=False).get("cancel_requested")):
                return True
        return False

    def _run_stream(self, claims: list[QueueClaim], concurrency: int, on_result: FinishHook | None) -> tuple[int, int, int]:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(self._run_one, claim): claim for claim in claims}
            pending = set(futures)
            completed = failed = retried = 0
            while pending:
                done, pending = wait(pending, timeout=self.heartbeat_interval_s, return_when=FIRST_COMPLETED)
                for future in done:
                    item_completed, item_failed, item_retried = self._finish_pair(futures[future], _future_result(future, futures[future]), on_result)
                    completed += item_completed
                    failed += item_failed
                    retried += item_retried
                if pending:
                    self._heartbeat([futures[future] for future in pending])
            return completed, failed, retried

    def _run_refill_stream(
        self,
        claims: list[QueueClaim],
        concurrency: int,
        on_result: FinishHook | None,
        *,
        node_id: str | None,
        batch_id: str | None,
        node_profile_ids: tuple[str, ...],
        max_node_depth: int,
        kv_capacity_bytes: int,
        kv_shard_layouts_by_profile: Mapping[str, PipelineProfile],
        batch_limits_by_service: Mapping[str, int],
        refill_low_watermark: int,
        share_compute_domain: bool = False,
        on_item_finished: Callable[[str], None] | None = None,
    ) -> tuple[int, int, int, int, int]:
        service_id = claims[0].selected_service_id
        compute_lease_id = claims[0].compute_lease_id
        low_watermark = max(1, min(int(refill_low_watermark), int(concurrency)))
        claimed = len(claims)
        prefilled = 0
        completed = failed = retried = 0
        refill_cancelled = False
        cancel_event = Event()
        finished: set[str] = set()
        pool = ThreadPoolExecutor(max_workers=concurrency)
        wait_for_workers = True
        try:
            futures = {pool.submit(self._run_refill_one, claim, cancel_event): claim for claim in claims}
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=self.heartbeat_interval_s, return_when=FIRST_COMPLETED)
                for future in done:
                    claim = futures[future]
                    item_completed, item_failed, item_retried = self._finish_pair(claim, _future_result(future, claim), on_result)
                    completed += item_completed
                    failed += item_failed
                    retried += item_retried
                    finished.add(claim.request_id)
                    _notify_item_finished(on_item_finished, claim.request_id)
                if pending and self._cancel_requested([futures[future] for future in pending]):
                    refill_cancelled = True
                    cancel_event.set()
                    item_completed, item_failed, item_retried, pending = _finish_cancelled_pending_futures(self, futures, pending, finished, on_result, on_item_finished)
                    completed += item_completed
                    failed += item_failed
                    retried += item_retried
                    if not pending:
                        wait_for_workers = False
                        break
                if not refill_cancelled and len(pending) <= low_watermark:
                    fill = max(0, int(concurrency) - len(pending))
                    if fill > 0:
                        more_prefilled, more_claims = self._claim_refill(
                            fill,
                            node_id=node_id,
                            batch_id=batch_id,
                            node_profile_ids=node_profile_ids,
                            max_node_depth=max_node_depth,
                            kv_capacity_bytes=kv_capacity_bytes,
                            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
                            batch_limits_by_service=batch_limits_by_service,
                            compute_lease_id=compute_lease_id,
                            selected_service_id=service_id,
                            allow_new_compute_lease=not pending,
                            share_compute_domain=share_compute_domain,
                        )
                        prefilled += more_prefilled
                        claimed += len(more_claims)
                        if more_claims:
                            compute_lease_id = more_claims[0].compute_lease_id
                        for claim in more_claims:
                            next_future = pool.submit(self._run_refill_one, claim, cancel_event)
                            futures[next_future] = claim
                            pending.add(next_future)
                if pending:
                    self._heartbeat([futures[future] for future in pending])
        finally:
            pool.shutdown(wait=wait_for_workers, cancel_futures=not wait_for_workers)
        return completed, failed, retried, claimed, prefilled

    def _claim_refill(
        self,
        limit: int,
        *,
        node_id: str | None,
        batch_id: str | None,
        node_profile_ids: tuple[str, ...],
        max_node_depth: int,
        kv_capacity_bytes: int,
        kv_shard_layouts_by_profile: Mapping[str, PipelineProfile],
        batch_limits_by_service: Mapping[str, int],
        compute_lease_id: str | None,
        selected_service_id: str | None,
        allow_new_compute_lease: bool,
        share_compute_domain: bool = False,
    ) -> tuple[int, list[QueueClaim]]:
        prefilled = self.queue.prepare_ready(
            node_id=node_id,
            eligible_profile_ids=node_profile_ids,
            batch_id=batch_id,
            limit=limit,
            leased_by=self.worker_id,
            lease_ttl_s=self.lease_ttl_s,
            max_node_depth=max_node_depth,
            kv_capacity_bytes=kv_capacity_bytes,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
            selected_service_id=selected_service_id,
            share_compute_domain=share_compute_domain,
        )
        claims = self.queue.claim_ready_batch(
            node_id=node_id,
            batch_id=batch_id,
            limit=limit,
            leased_by=self.worker_id,
            lease_ttl_s=self.lease_ttl_s,
            batch_linger_s=0.0,
            kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
            batch_limits_by_service=batch_limits_by_service,
            compute_lease_id=compute_lease_id,
            selected_service_id=selected_service_id,
            share_compute_domain=share_compute_domain,
        )
        if not claims and allow_new_compute_lease and compute_lease_id is not None and not share_compute_domain:
            claims = self.queue.claim_ready_batch(
                node_id=node_id,
                batch_id=batch_id,
                limit=limit,
                leased_by=self.worker_id,
                lease_ttl_s=self.lease_ttl_s,
                batch_linger_s=0.0,
                kv_shard_layouts_by_profile=kv_shard_layouts_by_profile,
                batch_limits_by_service=batch_limits_by_service,
                selected_service_id=selected_service_id,
            )
        return prefilled, claims

    def _await_with_heartbeat(self, future: Any, claims: list[QueueClaim]) -> dict[str, dict]:
        while not future.done():
            wait([future], timeout=self.heartbeat_interval_s)
            if not future.done():
                self._heartbeat(claims)
        return future.result()

    def _heartbeat(self, claims: list[QueueClaim]) -> None:
        active = [claim for claim in claims if claim.lease_id]
        if not active:
            return
        count = self.queue.heartbeat(lease_ids=[claim.lease_id for claim in active], lease_ttl_s=self.lease_ttl_s)
        if count == len(active):
            return
        lost = []
        for claim in active:
            state = str(self.queue.status(request_id=claim.request_id).get("state") or "")
            if state in _TERMINAL_STATES:
                continue
            refreshed = self.queue.heartbeat(lease_ids=[claim.lease_id], lease_ttl_s=self.lease_ttl_s)
            if refreshed == 1:
                continue
            state = str(self.queue.status(request_id=claim.request_id).get("state") or "")
            if state not in _TERMINAL_STATES:
                lost.append(f"{claim.request_id}:{state or 'unknown'}")
        if lost:
            raise RuntimeError(f"lost queue lease during heartbeat: refreshed {count}/{len(active)}; unresolved={','.join(lost[:8])}")

    def _run_one(self, claim: QueueClaim) -> dict[str, Any]:
        if claim.request_kind != "model" or claim.request is None:
            return _failure(claim, "worker cannot run CPU claim without CPU batch path")
        if self._claim_cancelled_or_terminal(claim):
            return _cancelled(claim)
        profile = self.registry.get(claim.selected_profile_id)
        if hasattr(self.runner, "run_one_on_node"):
            result = self.runner.run_one_on_node(claim.request, profile, claim.selected_node_id)  # type: ignore[attr-defined]
        else:
            result = self.runner.run_one(claim.request, profile)
        return _result_for_claim(claim, result)

    def _run_refill_one(self, claim: QueueClaim, cancel_event: Event) -> dict[str, Any]:
        if claim.request_kind != "model" or claim.request is None:
            return _failure(claim, "worker cannot run CPU claim without CPU batch path")
        if self._claim_cancelled_or_terminal(claim):
            return _cancelled(claim)
        if not hasattr(self.runner, "run_many_on_node_incremental"):
            return self._run_one(claim)
        profile = self.registry.get(claim.selected_profile_id)
        results: dict[str, dict[str, Any]] = {}

        def push_result(request_id: str, result: dict[str, Any]) -> None:
            results[request_id] = result

        try:
            batch = self.runner.run_many_on_node_incremental(
                [claim.request],
                profile,
                claim.selected_node_id,
                concurrency=1,
                on_result=push_result,
                on_delta=lambda request_id, text, payload: _push_stream_delta(self.queue, request_id, text, payload),
                cancel_event=cancel_event,
            )  # type: ignore[attr-defined]
        except Exception as exc:
            return _failure(claim, str(exc))
        result = results.get(claim.request_id)
        if result is None and isinstance(batch, dict):
            result = batch.get(claim.request_id)
        return _result_for_claim(claim, result)

    def _claim_cancelled_or_terminal(self, claim: QueueClaim) -> bool:
        status = self.queue.status(request_id=claim.request_id, refresh=False)
        state = str(status.get("state") or "")
        return bool(status.get("cancel_requested")) or state in _TERMINAL_STATES

    def _run_cpu_claims(self, claims: list[QueueClaim], concurrency: int) -> list[tuple[QueueClaim, dict[str, Any]]]:
        service = claims[0].service_name or ""
        items, timeout_s = _cpu_items_and_timeout(claims, self.lease_ttl_s)
        try:
            rows = _cpu_service().run_batch({"service": service, "items": items, "concurrency": concurrency, "timeout_s": timeout_s}).get("results", [])
        except Exception as exc:
            rows = [{"ok": False, "error": str(exc)} for _ in claims]
        out = []
        for index, claim in enumerate(claims):
            row = rows[index] if index < len(rows) and isinstance(rows[index], dict) else {"ok": False, "error": "CPU batch omitted result"}
            out.append((claim, {"format": "ds4-cpu-service-result-v1", "request_id": claim.request_id, "status": "completed" if row.get("ok") else "failed", "service": service, "output": row}))
        return out


def _can_batch_models(runner: Runner, claims: list[QueueClaim]) -> bool:
    return bool(claims and claims[0].request_kind == "model" and hasattr(runner, "run_many_on_node") and all(claim.request_kind == "model" and claim.selected_profile_id == claims[0].selected_profile_id and claim.selected_node_id == claims[0].selected_node_id and claim.selected_service_id == claims[0].selected_service_id for claim in claims))


def _can_batch_models_incremental(runner: Runner, claims: list[QueueClaim]) -> bool:
    return bool(_can_batch_models(runner, claims) and hasattr(runner, "run_many_on_node_incremental"))


def _push_stream_delta(queue: Any, request_id: str, text: str, payload: dict[str, Any] | None) -> None:
    if hasattr(queue, "stream_delta"):
        queue.stream_delta(request_id=request_id, text=text, payload=payload or {})


def _notify_item_finished(callback: Callable[[str], None] | None, request_id: str) -> None:
    if callback is not None:
        callback(request_id)


def _finish_cancelled_or_terminal_pending(worker: BatchWorker, claims: list[QueueClaim], finished: set[str], on_result: FinishHook | None, on_item_finished: Callable[[str], None] | None) -> tuple[int, int, int]:
    completed = failed = retried = 0
    for claim in claims:
        if claim.request_id in finished:
            continue
        status = worker.queue.status(request_id=claim.request_id, refresh=False)
        state = str(status.get("state") or "")
        if not bool(status.get("cancel_requested")) and state not in _TERMINAL_STATES:
            continue
        item_completed, item_failed, item_retried = worker._finish_pair(claim, _cancelled(claim), on_result)
        completed += item_completed
        failed += item_failed
        retried += item_retried
        finished.add(claim.request_id)
        _notify_item_finished(on_item_finished, claim.request_id)
    return completed, failed, retried


def _finish_cancelled_pending_futures(worker: BatchWorker, futures: Mapping[Any, QueueClaim], pending: set[Any], finished: set[str], on_result: FinishHook | None, on_item_finished: Callable[[str], None] | None) -> tuple[int, int, int, set[Any]]:
    claims = []
    for future in pending:
        claim = futures[future]
        state = str(worker.queue.status(request_id=claim.request_id, refresh=False).get("state") or "")
        if state in _TERMINAL_STATES:
            claims.append(claim)
    completed, failed, retried = _finish_cancelled_or_terminal_pending(worker, claims, finished, on_result, on_item_finished)
    pending = {future for future in pending if futures[future].request_id not in finished}
    return completed, failed, retried, pending


def _service_refill_low_watermark(service_id: str | None, values: Mapping[str, int]) -> int:
    if service_id is None:
        return int(values.get("", 0) or values.get("*", 0) or 0)
    return int(values.get(str(service_id), 0) or values.get("*", 0) or 0)


def _result_for_claim(claim: QueueClaim, result: dict[str, Any] | None) -> dict[str, Any]:
    out = result or _failure(claim, "batch runner omitted request result")
    if claim.selected_node_id:
        out["selected_node"] = {
            "node_id": claim.selected_node_id,
            "node_ids": list(claim.selected_node_ids or (claim.selected_node_id,)),
            "service_id": claim.selected_service_id,
            "compute_domain": claim.selected_compute_domain,
        }
    return out


def _future_result(future: Any, claim: QueueClaim) -> dict[str, Any]:
    try:
        return _result_for_claim(claim, future.result())
    except Exception as exc:
        return _failure(claim, str(exc))


def _failure(claim: QueueClaim, error: str) -> dict[str, Any]:
    return {"format": "ds4-inference-failure-v1", "request_id": claim.request_id, "status": "failed", "error": error}


def _cancelled(claim: QueueClaim) -> dict[str, Any]:
    return {"format": "ds4-inference-cancelled-v1", "request_id": claim.request_id, "status": "cancelled", "reason": "cancelled before model dispatch"}


def _summary(claimed: int, completed: int, failed: int, reap: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return dict({"format": "ds4-inference-queue-v1", "state": "worked" if claimed else "idle", "claimed_count": claimed, "completed_count": completed, "failed_count": failed, "lost_lease_count": 0, "reaped": reap}, **extra)


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


def _cpu_service() -> Any:
    global _CPU_SERVICE
    if _CPU_SERVICE is None:
        from ds4_tools.cpu_batch import CpuBatchService
        _CPU_SERVICE = CpuBatchService()
    return _CPU_SERVICE
