from __future__ import annotations

from typing import Any, Iterable

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


def append_node_claim_filter(clauses: list[str], params: list[Any], *, node_id: str | None, include_unassigned: bool, eligible_profile_ids: Iterable[str] | None) -> None:
    if node_id is None:
        return
    eligible = tuple(str(profile_id) for profile_id in (eligible_profile_ids or ()) if str(profile_id))
    if include_unassigned and eligible:
        placeholders = ",".join("?" for _ in eligible)
        clauses.append(f"(selected_node_id = ? or (selected_node_id is null and selected_profile_id in ({placeholders})))")
        params.append(node_id)
        params.extend(eligible)
    elif include_unassigned and eligible_profile_ids is None:
        clauses.append("(selected_node_id = ? or selected_node_id is null)")
        params.append(node_id)
    else:
        clauses.append("selected_node_id = ?")
        params.append(node_id)


def node_model_depth_allowance(conn: Any, *, node_id: str, max_node_depth: int) -> int:
    row = conn.execute(
        """
        select count(*) n
        from requests
        where state in ('queued','running') and selected_node_id = ? and request_kind = 'model'
        """,
        (node_id,),
    ).fetchone()
    return max(0, max_node_depth - int(row["n"] if row is not None else 0))
