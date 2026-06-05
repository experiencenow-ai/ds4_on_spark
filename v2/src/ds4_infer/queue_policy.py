from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import InferenceRequest

DEFAULT_QUEUE_PRIORITY = 10
IMMEDIATE_QUEUE_PRIORITY = 0
_REQUIRED_SERVICE_SCHEDULER_KEYS = (
    "batch_linger_s",
    "compute_lease_quantum_s",
    "dispatch_quantum",
    "queue_limit",
    "refill_low_watermark",
)


@dataclass(frozen=True)
class SchedulerPolicy:
    batch_linger_by_service: dict[str, float]
    batch_limits_by_service: dict[str, int]
    compute_lease_quantum_s_by_service: dict[str, float]
    dispatch_quanta_by_service: dict[str, int]
    refill_low_watermarks_by_service: dict[str, int]

    @classmethod
    def from_topology(cls, topology: Any) -> "SchedulerPolicy":
        batch_linger: dict[str, float] = {}
        batch_limits: dict[str, int] = {}
        compute_quanta: dict[str, float] = {}
        dispatch_quanta: dict[str, int] = {}
        refill_low_watermarks: dict[str, int] = {}
        for service in topology.pipeline_services.values():
            scheduler = dict(service.scheduler)
            missing = [key for key in _REQUIRED_SERVICE_SCHEDULER_KEYS if key not in scheduler]
            if missing:
                raise ValueError(f"pipeline service {service.service_id!r} scheduler missing fields: {missing}")
            service_id = str(service.service_id)
            batch_linger[service_id] = max(0.0, float(scheduler["batch_linger_s"]))
            batch_limits[service_id] = max(1, int(scheduler["queue_limit"]))
            compute_quanta[service_id] = max(0.0, float(scheduler["compute_lease_quantum_s"]))
            dispatch_quanta[service_id] = max(1, int(scheduler["dispatch_quantum"]))
            refill_low_watermarks[service_id] = max(0, int(scheduler["refill_low_watermark"]))
        return cls(
            batch_linger_by_service=batch_linger,
            batch_limits_by_service=batch_limits,
            compute_lease_quantum_s_by_service=compute_quanta,
            dispatch_quanta_by_service=dispatch_quanta,
            refill_low_watermarks_by_service=refill_low_watermarks,
        )


def validated_priority(priority: int | None, *, immediate: bool | None = None) -> int | None:
    if priority is None:
        if immediate is None:
            return None
        return IMMEDIATE_QUEUE_PRIORITY if immediate else DEFAULT_QUEUE_PRIORITY
    value = int(priority)
    if value < 0:
        raise ValueError("priority must be non-negative")
    return value


def request_priority(request: InferenceRequest, *, priority_override: int | None) -> int:
    if priority_override is not None:
        return priority_override
    if request.priority is not None:
        return validated_priority(request.priority)
    return IMMEDIATE_QUEUE_PRIORITY if request.immediate else DEFAULT_QUEUE_PRIORITY


def job_batch_id(*, batch_id: str | None, job_id: str | None) -> str | None:
    if batch_id is not None and job_id is not None and batch_id != job_id:
        raise ValueError("batch_id and job_id must match when both are provided")
    return batch_id if batch_id is not None else job_id
