from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import threading
import time
from typing import Any

from .pipelines import pipeline_service_batch_limit
from .queue import QueueClaim
from .topology import SparkTopology


@dataclass
class PendingDispatcherCohort:
    claims: list[QueueClaim]
    unfinished_request_ids: set[str]
    service_id: str | None = None
    profile_id: str | None = None
    compute_domain: str | None = None
    admission_mode: str = "cohort"
    initial_count: int = 0
    claimed_count: int = 0
    finished_count: int = 0
    submitted_at: float = field(default_factory=time.time)
    last_finished_at: float | None = None
    lock: Any = field(default_factory=threading.Lock)

    @classmethod
    def from_claims(cls, claims: list[QueueClaim], *, admission_mode: str = "cohort") -> "PendingDispatcherCohort":
        first = claims[0] if claims else None
        return cls(
            claims=list(claims),
            unfinished_request_ids={claim.request_id for claim in claims},
            service_id=first.selected_service_id if first is not None else None,
            profile_id=first.selected_profile_id if first is not None else None,
            compute_domain=first.selected_compute_domain if first is not None else None,
            admission_mode=str(admission_mode or "cohort"),
            initial_count=len(claims),
            claimed_count=len(claims),
        )

    def mark_finished(self, request_id: str) -> None:
        with self.lock:
            before = len(self.unfinished_request_ids)
            self.unfinished_request_ids.discard(str(request_id))
            if len(self.unfinished_request_ids) != before:
                self.finished_count += 1
                self.last_finished_at = time.time()

    def active_count(self) -> int:
        with self.lock:
            return len(self.unfinished_request_ids)

    def active_claims(self) -> list[QueueClaim]:
        with self.lock:
            active = set(self.unfinished_request_ids)
        return [claim for claim in self.claims if claim.request_id in active]

    def status(self) -> dict[str, Any]:
        now = time.time()
        with self.lock:
            unfinished = len(self.unfinished_request_ids)
            finished = int(self.finished_count)
            last_finished = self.last_finished_at
        return {
            "service_id": self.service_id,
            "profile_id": self.profile_id,
            "compute_domain": self.compute_domain,
            "admission_mode": self.admission_mode,
            "initial_count": self.initial_count,
            "claimed_count": self.claimed_count,
            "initial_unfinished_count": unfinished,
            "active_count": unfinished,
            "finished_count": finished,
            "age_s": round(max(0.0, now - float(self.submitted_at)), 3),
            "last_finished_age_s": None if last_finished is None else round(max(0.0, now - float(last_finished)), 3),
        }


@dataclass
class ResidentServicePlan:
    service_id: str
    profile_id: str
    compute_domain: str
    target_active: int
    queue_depth_target: int
    low_watermark: int
    max_cohort_size: int
    batch_linger_s: float
    max_running_batches_per_compute_domain: int = 0
    max_running_batches_per_service: int = 0
    ready_shape_bucketing: bool = False
    ready_shape_lookahead: int = 1
    weight: float = 1.0
    admission_mode: str = "resident_multimodel_weighted_deficit"
    deficit: float = 0.0
    submitted_count: int = 0
    completed_count: int = 0
    last_claimed_count: int = 0
    last_claimed_at: float = 0.0

    def credit(self, elapsed_s: float) -> None:
        credit = max(0.0, elapsed_s) * max(0.01, self.weight) * max(1, self.target_active)
        self.deficit = min(float(self.target_active) * 4.0, self.deficit + credit)

    def charge(self, count: int) -> None:
        count = max(0, int(count))
        self.deficit -= float(count)
        self.submitted_count += count
        self.last_claimed_count = count
        self.last_claimed_at = time.time()


def resident_service_plans(topology: SparkTopology, *, entry_node_id: str, default_batch_linger_s: float) -> dict[str, ResidentServicePlan]:
    weights = _json_float_env("DS4_API_SERVICE_WEIGHTS_JSON")
    targets = _json_int_env("DS4_API_SERVICE_TARGETS_JSON")
    queue_targets = _json_int_env("DS4_API_SERVICE_QUEUE_DEPTH_TARGETS_JSON")
    lows = _json_int_env("DS4_API_SERVICE_LOW_WATERMARKS_JSON")
    cohort_sizes = _json_int_env("DS4_API_SERVICE_MAX_COHORTS_JSON")
    linger = _json_float_env("DS4_API_SERVICE_LINGER_JSON")
    admission_modes = _json_str_env("DS4_API_SERVICE_ADMISSION_MODES_JSON")
    default_admission_mode = os.environ.get("DS4_API_SERVICE_ADMISSION_MODE") or os.environ.get("DS4_API_RESIDENT_ADMISSION_MODE") or ""
    active = active_resident_service_ids(topology)
    plans: dict[str, ResidentServicePlan] = {}
    for service in topology.pipeline_services.values():
        if service.entry_node_id != entry_node_id:
            continue
        if active is not None and service.service_id not in active:
            continue
        plans[service.service_id] = _resident_service_plan(
            service,
            default_batch_linger_s=default_batch_linger_s,
            weights=weights,
            targets=targets,
            queue_targets=queue_targets,
            lows=lows,
            cohort_sizes=cohort_sizes,
            linger=linger,
            admission_modes=admission_modes,
            default_admission_mode=default_admission_mode,
        )
    return plans


def active_resident_service_ids(topology: SparkTopology) -> set[str] | None:
    raw_env = os.environ.get("DS4_API_RESIDENT_SERVICE_IDS") or os.environ.get("DS4_API_ACTIVE_RESIDENT_SERVICES")
    if raw_env:
        return _parse_service_ids(raw_env)
    raw = topology.routing_policy.get("active_resident_service_ids")
    if raw is None:
        return None
    if isinstance(raw, str):
        return _parse_service_ids(raw)
    if isinstance(raw, list):
        return {str(item) for item in raw if str(item)}
    return None


def service_target_active(service: Any) -> int:
    return pipeline_service_batch_limit(service)


def resident_service_order(plans: dict[str, ResidentServicePlan], active_by_service: dict[str, int]) -> list[ResidentServicePlan]:
    def key(plan: ResidentServicePlan) -> tuple[float, float, float, str]:
        active = int(active_by_service.get(plan.service_id, 0))
        ratio = active / max(1, int(plan.queue_depth_target))
        below_low = 0.0 if active < plan.low_watermark else 1.0
        return (below_low, ratio, -float(plan.deficit), plan.service_id)
    return sorted(plans.values(), key=key)


def pending_claims(pending: dict[Any, Any]) -> list[QueueClaim]:
    claims: list[QueueClaim] = []
    for cohort in pending.values():
        claims.extend(pending_cohort(cohort).active_claims())
    return claims


def pending_claim_count(pending: dict[Any, Any]) -> int:
    return sum(pending_cohort(cohort).active_count() for cohort in pending.values())


def pending_claim_count_by_service(pending: dict[Any, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in pending.values():
        cohort = pending_cohort(value)
        service_id = str(cohort.service_id or "_unknown")
        counts[service_id] = counts.get(service_id, 0) + cohort.active_count()
    return counts


def pending_cohort_count_by_compute_domain(pending: dict[Any, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in pending.values():
        cohort = pending_cohort(value)
        if cohort.active_count() <= 0:
            continue
        domain = str(cohort.compute_domain or "")
        if not domain:
            continue
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def pending_cohort_count_by_service(pending: dict[Any, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in pending.values():
        cohort = pending_cohort(value)
        if cohort.active_count() <= 0:
            continue
        service_id = str(cohort.service_id or "")
        if not service_id:
            continue
        counts[service_id] = counts.get(service_id, 0) + 1
    return counts


def pending_cohort_details(pending: dict[Any, Any]) -> list[dict[str, Any]]:
    return [pending_cohort(value).status() for value in pending.values()]


def pending_cohort(value: Any) -> PendingDispatcherCohort:
    if isinstance(value, PendingDispatcherCohort):
        return value
    return PendingDispatcherCohort.from_claims(list(value))


def plan_uses_rolling_admission(plan: ResidentServicePlan) -> bool:
    mode = str(plan.admission_mode or "").lower()
    return mode in {"resident_multimodel_rolling_refill", "rolling_refill", "rolling"}


def _resident_service_plan(service: Any, *, default_batch_linger_s: float, weights: dict[str, float], targets: dict[str, int], queue_targets: dict[str, int], lows: dict[str, int], cohort_sizes: dict[str, int], linger: dict[str, float], admission_modes: dict[str, str], default_admission_mode: str) -> ResidentServicePlan:
    service_id = service.service_id
    target = max(1, int(targets.get(service_id, targets.get(service.profile_id, service_target_active(service)))))
    queue_target = max(target, int(queue_targets.get(service_id, queue_targets.get(service.profile_id, _scheduler_int(service, ("queue_depth_target", "vllm_queue_depth_target", "submit_queue_depth_target"), target)))))
    low = int(lows.get(service_id, lows.get(service.profile_id, int(service.scheduler.get("refill_low_watermark") or 0))))
    if low <= 0:
        low = max(1, int(queue_target * 0.75))
    max_cohort_default = _scheduler_int(service, ("dispatch_batch_limit", "max_dispatch_cohort", "queue_depth_target", "vllm_queue_depth_target"), pipeline_service_batch_limit(service))
    max_cohort = max(1, int(cohort_sizes.get(service_id, cohort_sizes.get(service.profile_id, max_cohort_default))))
    max_domain_batches = max(0, _scheduler_int(service, ("max_running_batches_per_compute_domain",), 0))
    max_service_batches = max(0, _scheduler_int(service, ("max_running_batches_per_service", "max_running_same_service_batches"), 0))
    service_linger = float(linger.get(service_id, linger.get(service.profile_id, _scheduler_linger(service, default_batch_linger_s))))
    admission_mode = str(admission_modes.get(service_id, admission_modes.get(service.profile_id, default_admission_mode or service.scheduler.get("admission_mode") or "resident_multimodel_weighted_deficit")))
    shape_bucketing = bool(service.scheduler.get("ready_shape_bucketing", False))
    shape_lookahead = max(1, _scheduler_int(service, ("ready_shape_lookahead",), 1))
    return ResidentServicePlan(
        service_id=service_id,
        profile_id=service.profile_id,
        compute_domain=service.compute_domain,
        target_active=target,
        queue_depth_target=queue_target,
        low_watermark=min(queue_target, max(1, low)),
        max_cohort_size=max_cohort,
        max_running_batches_per_compute_domain=max_domain_batches,
        max_running_batches_per_service=max_service_batches,
        batch_linger_s=max(0.0, service_linger),
        ready_shape_bucketing=shape_bucketing,
        ready_shape_lookahead=shape_lookahead,
        weight=max(0.01, float(weights.get(service_id, weights.get(service.profile_id, service.scheduler.get("resident_weight") or 1.0)))),
        admission_mode=admission_mode,
    )


def _scheduler_linger(service: Any, default_batch_linger_s: float) -> float:
    raw = service.scheduler.get("batch_linger_s") if service.scheduler.get("batch_linger_s") is not None else default_batch_linger_s
    return float(raw)


def _scheduler_int(service: Any, keys: tuple[str, ...], default: int) -> int:
    scheduler = getattr(service, "scheduler", {}) or {}
    if not isinstance(scheduler, dict):
        return int(default)
    for key in keys:
        value = scheduler.get(key)
        if value is not None:
            return int(value)
    return int(default)


def _json_int_env(name: str) -> dict[str, int]:
    parsed = _json_env(name)
    out: dict[str, int] = {}
    for key, value in parsed.items():
        try:
            out[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def _json_float_env(name: str) -> dict[str, float]:
    parsed = _json_env(name)
    out: dict[str, float] = {}
    for key, value in parsed.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def _json_str_env(name: str) -> dict[str, str]:
    parsed = _json_env(name)
    out: dict[str, str] = {}
    for key, value in parsed.items():
        text = str(value).strip()
        if text:
            out[str(key)] = text
    return out


def _json_env(name: str) -> dict[str, Any]:
    raw = os.environ.get(name)
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_service_ids(raw: str) -> set[str]:
    return {item.strip() for item in raw.replace(";", ",").split(",") if item.strip()}
