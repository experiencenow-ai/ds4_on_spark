from __future__ import annotations

import os
from typing import Any

from .dispatcher_resident import active_resident_service_ids, service_target_active
from .env_utils import env_bool as _env_bool, env_int as _env_int
from .topology import SparkTopology

READINESS_FORMAT = "ds4-deployment-readiness-v1"
DEFAULT_FIRST3_SERVICES = ("qwen27_bf16_pp8", "gemma4_26b_a4b_pp8", "dsv4_flash_pp8")


def deployment_readiness(
    *,
    topology: SparkTopology,
    dispatcher_window: int,
    dispatcher_refill_batch: int,
    dispatcher_cohort_workers: int,
    resident_multimodel: bool,
) -> dict[str, Any]:
    strict = _env_bool("DS4_API_DEPLOYMENT_STRICT", False)
    active_ids = active_resident_service_ids(topology)
    services = _active_services(topology, active_ids)
    targets = {service.service_id: service_target_active(service) for service in services}
    largest = max(targets.values(), default=0)
    target_sum = sum(targets.values())
    checks: list[dict[str, Any]] = []
    _active_service_checks(checks, topology=topology, active_ids=active_ids, services=services, targets=targets)
    _scheduler_checks(
        checks,
        dispatcher_window=dispatcher_window,
        dispatcher_refill_batch=dispatcher_refill_batch,
        dispatcher_cohort_workers=dispatcher_cohort_workers,
        resident_multimodel=resident_multimodel,
        service_count=len(services),
        largest=largest,
        target_sum=target_sum,
    )
    for service in services:
        _pipeline_checks(checks, service)
    _jit_kv_checks(checks, strict=strict)
    return _readiness_payload(
        checks=checks,
        strict=strict,
        services=services,
        targets=targets,
        target_sum=target_sum,
        largest=largest,
        dispatcher_window=dispatcher_window,
        dispatcher_refill_batch=dispatcher_refill_batch,
        dispatcher_cohort_workers=dispatcher_cohort_workers,
    )


def _active_service_checks(checks: list[dict[str, Any]], *, topology: SparkTopology, active_ids: set[str] | None, services: list[Any], targets: dict[str, int]) -> None:
    _check(checks, bool(services), "active_resident_services_present", "at least one active resident service is configured")
    if active_ids is not None:
        missing = sorted(active_ids - set(topology.pipeline_services))
        _check(checks, not missing, "active_resident_services_known", "active resident services exist in topology", details={"missing": missing})
    _check(
        checks,
        set(targets) == set(DEFAULT_FIRST3_SERVICES),
        "first3_resident_service_set",
        "first 3x resident set is Qwen BF16, Gemma4 26B-A4B, and DSV4",
        details={"expected": list(DEFAULT_FIRST3_SERVICES), "actual": sorted(targets)},
        severity="warning",
    )


def _scheduler_checks(
    checks: list[dict[str, Any]],
    *,
    dispatcher_window: int,
    dispatcher_refill_batch: int,
    dispatcher_cohort_workers: int,
    resident_multimodel: bool,
    service_count: int,
    largest: int,
    target_sum: int,
) -> None:
    _check(
        checks,
        int(dispatcher_window) >= max(1, largest),
        "dispatcher_window_covers_largest_service",
        "dispatcher window covers the largest resident target",
        details={"window": int(dispatcher_window), "largest_target_active": largest},
    )
    _check(
        checks,
        int(dispatcher_window) >= target_sum,
        "dispatcher_window_covers_sum_targets",
        "dispatcher window can keep every active resident target full at once",
        details={"window": int(dispatcher_window), "target_active_sum": target_sum},
        severity="warning",
    )
    _check(
        checks,
        int(dispatcher_refill_batch) >= max(1, largest),
        "refill_batch_covers_largest_service",
        "refill batch covers the largest resident cohort",
        details={"refill_batch": int(dispatcher_refill_batch), "largest_target_active": largest},
    )
    _check(
        checks,
        bool(resident_multimodel) or service_count <= 1,
        "resident_multimodel_enabled",
        "resident multimodel scheduler is enabled for multi-service deployment",
        details={"service_count": service_count, "resident_multimodel": bool(resident_multimodel)},
    )
    _check(
        checks,
        int(dispatcher_cohort_workers) >= min(max(1, service_count), 4),
        "cohort_worker_sanity",
        "cohort worker pool can make progress on the active service set",
        details={"cohort_workers": int(dispatcher_cohort_workers), "service_count": service_count},
        severity="warning",
    )


def _readiness_payload(
    *,
    checks: list[dict[str, Any]],
    strict: bool,
    services: list[Any],
    targets: dict[str, int],
    target_sum: int,
    largest: int,
    dispatcher_window: int,
    dispatcher_refill_batch: int,
    dispatcher_cohort_workers: int,
) -> dict[str, Any]:
    errors = [item for item in checks if item["severity"] == "error" and not item["ok"]]
    warnings = [item for item in checks if item["severity"] == "warning" and not item["ok"]]
    return {
        "format": READINESS_FORMAT,
        "ready": not errors,
        "strict": strict,
        "active_resident_service_ids": [service.service_id for service in services],
        "resident_service_targets": targets,
        "target_active_sum": target_sum,
        "largest_target_active": largest,
        "dispatcher_window": int(dispatcher_window),
        "dispatcher_refill_batch": int(dispatcher_refill_batch),
        "dispatcher_cohort_workers": int(dispatcher_cohort_workers),
        "hard_error_count": len(errors),
        "warning_count": len(warnings),
        "checks": checks,
    }


def default_dispatch_window(topology: SparkTopology) -> int:
    services = _active_services(topology, active_resident_service_ids(topology))
    values = [service_target_active(service) for service in services]
    return max(64, sum(values) if values else 0)


def default_cohort_workers(topology: SparkTopology) -> int:
    services = _active_services(topology, active_resident_service_ids(topology))
    return max(4, min(32, len(services) * 4))


def _active_services(topology: SparkTopology, active_ids: set[str] | None) -> list[Any]:
    services = []
    for service in topology.pipeline_services.values():
        if active_ids is not None and service.service_id not in active_ids:
            continue
        services.append(service)
    return services


def _pipeline_checks(checks: list[dict[str, Any]], service: Any) -> None:
    _check(
        checks,
        len(service.node_ids) == int(service.pipeline_parallel_size),
        f"{service.service_id}:pipeline_node_count",
        "pipeline node count matches PP size",
        details={"node_count": len(service.node_ids), "pipeline_parallel_size": int(service.pipeline_parallel_size)},
    )
    _check(
        checks,
        len(service.layer_partition) == int(service.pipeline_parallel_size),
        f"{service.service_id}:layer_partition_width",
        "layer partition width matches PP size",
        details={"partition": list(service.layer_partition), "pipeline_parallel_size": int(service.pipeline_parallel_size)},
    )
    _check(
        checks,
        sum(int(item) for item in service.layer_partition) == int(service.total_layers),
        f"{service.service_id}:layer_partition_sum",
        "layer partition sums to total layers",
        details={"partition": list(service.layer_partition), "total_layers": int(service.total_layers)},
    )
    _check(
        checks,
        all(int(item) > 0 for item in service.layer_partition),
        f"{service.service_id}:no_empty_pipeline_stages",
        "no pipeline stage has zero layers",
        details={"partition": list(service.layer_partition)},
    )


def _jit_kv_checks(checks: list[dict[str, Any]], *, strict: bool) -> None:
    token = os.environ.get("DS4_API_JIT_KV_PREFETCH_TOKEN", "")
    endpoint_enabled = _env_bool("DS4_API_JIT_KV_PREFETCH_API", bool(token))
    _check(
        checks,
        _env_bool("DS4_API_JIT_KV_RECOVER_ON_STARTUP", True),
        "jit_kv_startup_recovery_enabled",
        "JIT KV startup recovery is enabled",
        severity="error" if strict else "warning",
    )
    _check(
        checks,
        _env_bool("DS4_API_JIT_KV_CIRCUIT_BREAKER", True),
        "jit_kv_circuit_breaker_enabled",
        "JIT KV circuit breaker is enabled",
        severity="error" if strict else "warning",
    )
    _check(
        checks,
        endpoint_enabled,
        "jit_kv_prefetch_gate_enabled",
        "vLLM DS4 KV prefetch endpoint use is enabled",
        severity="error" if strict else "warning",
    )
    _check(
        checks,
        bool(token),
        "jit_kv_prefetch_token_present",
        "DS4 has a token for vLLM DS4 KV prefetch",
        severity="error" if strict else "warning",
    )
    block_tokens = max(1, _env_int("DS4_API_JIT_KV_BLOCK_SIZE_TOKENS", 16))
    min_tokens = _env_int("DS4_API_JIT_KV_MIN_PREFIX_TOKENS", max(1, _env_int("DS4_PIPELINE_PRESTAGE_COMMON_PREFIX_MIN_CHARS", 1024) // 4))
    _check(
        checks,
        min_tokens >= block_tokens,
        "jit_kv_min_prefix_covers_block",
        "minimum auto-KV prefix is at least one cache block",
        details={"min_prefix_tokens": min_tokens, "block_size_tokens": block_tokens},
        severity="error" if strict else "warning",
    )


def _check(
    checks: list[dict[str, Any]],
    ok: bool,
    name: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    severity: str = "error",
) -> None:
    checks.append({"name": name, "ok": bool(ok), "severity": severity, "message": message, "details": dict(details or {})})
