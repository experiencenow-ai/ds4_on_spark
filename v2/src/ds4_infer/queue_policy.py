from __future__ import annotations

from .schemas import InferenceRequest

DEFAULT_QUEUE_PRIORITY = 10
IMMEDIATE_QUEUE_PRIORITY = 0


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
