from __future__ import annotations

import os
from typing import Any

from .dispatcher_resident import active_resident_service_ids, service_target_active
from .env_utils import env_bool as _env_bool, env_int as _env_int
from .topology import SparkTopology

READINESS_FORMAT = "ds4-deployment-readiness-v1"
DEFAULT_FIRST3_SERVICES = ("qwen27_bf16_pp8", "gemma4_26b_a4b_pp8", "dsv4_flash_pp8")
FIRST3_GPU_UTILIZATION_HARD_CAP = 0.85
FIRST3_CACHE_CONNECTORS = {
    "qwen27_bf16_pp8": "lmcache",
    "gemma4_26b_a4b_pp8": "lmcache",
    "dsv4_flash_pp8": "simple_cpu_offload",
}
FIRST3_CACHE_BACKENDS = {
    "qwen27_bf16_pp8": "lmcache_hma",
    "gemma4_26b_a4b_pp8": "lmcache_hma",
    "dsv4_flash_pp8": "dsv4_hma",
}
FIRST3_GPU_UTILIZATION_FLOORS = {
    "qwen27_bf16_pp8": 0.20,
    "gemma4_26b_a4b_pp8": 0.20,
    "dsv4_flash_pp8": 0.28,
}


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
    queue_depth_targets = {service.service_id: _service_queue_depth_target(service) for service in services}
    largest = max(targets.values(), default=0)
    target_sum = sum(targets.values())
    largest_queue_depth = max(queue_depth_targets.values(), default=0)
    queue_depth_sum = sum(queue_depth_targets.values())
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
        largest_queue_depth=largest_queue_depth,
        queue_depth_sum=queue_depth_sum,
    )
    for service in services:
        _pipeline_checks(checks, service)
    _external_kv_checks(checks, services=services)
    gpu_budget = _gpu_budget_by_service(services)
    _resident_gpu_budget_checks(checks, services=services, gpu_budget=gpu_budget)
    _jit_kv_checks(checks, services=services, strict=strict)
    return _readiness_payload(
        checks=checks,
        strict=strict,
        services=services,
        targets=targets,
        queue_depth_targets=queue_depth_targets,
        target_sum=target_sum,
        largest=largest,
        queue_depth_sum=queue_depth_sum,
        largest_queue_depth=largest_queue_depth,
        dispatcher_window=dispatcher_window,
        dispatcher_refill_batch=dispatcher_refill_batch,
        dispatcher_cohort_workers=dispatcher_cohort_workers,
        gpu_budget=gpu_budget,
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
    largest_queue_depth: int,
    queue_depth_sum: int,
) -> None:
    _scheduler_window_checks(
        checks,
        dispatcher_window=dispatcher_window,
        largest=largest,
        target_sum=target_sum,
        largest_queue_depth=largest_queue_depth,
        queue_depth_sum=queue_depth_sum,
    )
    _scheduler_refill_checks(
        checks,
        dispatcher_refill_batch=dispatcher_refill_batch,
        largest=largest,
        largest_queue_depth=largest_queue_depth,
    )
    _check(
        checks,
        bool(resident_multimodel) or service_count <= 1,
        "resident_multimodel_enabled",
        "resident multimodel scheduler is enabled for multi-service deployment",
        details={"service_count": service_count, "resident_multimodel": bool(resident_multimodel)},
    )
    _scheduler_worker_checks(
        checks,
        dispatcher_cohort_workers=dispatcher_cohort_workers,
        service_count=service_count,
        largest=largest,
        target_sum=target_sum,
        largest_queue_depth=largest_queue_depth,
    )


def _scheduler_window_checks(
    checks: list[dict[str, Any]],
    *,
    dispatcher_window: int,
    largest: int,
    target_sum: int,
    largest_queue_depth: int,
    queue_depth_sum: int,
) -> None:
    _check(checks, int(dispatcher_window) >= max(1, largest), "dispatcher_window_covers_largest_service", "dispatcher window covers the largest resident target", details={"window": int(dispatcher_window), "largest_target_active": largest})
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
        int(dispatcher_window) >= max(1, largest_queue_depth),
        "dispatcher_window_covers_largest_service_queue_depth",
        "dispatcher window covers the largest resident submit queue depth",
        details={"window": int(dispatcher_window), "largest_queue_depth_target": largest_queue_depth},
    )
    _check(
        checks,
        int(dispatcher_window) >= queue_depth_sum,
        "dispatcher_window_covers_sum_queue_depths",
        "dispatcher window can hold every active resident submit queue depth at once",
        details={"window": int(dispatcher_window), "queue_depth_target_sum": queue_depth_sum},
        severity="warning",
    )


def _scheduler_refill_checks(
    checks: list[dict[str, Any]],
    *,
    dispatcher_refill_batch: int,
    largest: int,
    largest_queue_depth: int,
) -> None:
    _check(
        checks,
        int(dispatcher_refill_batch) >= max(1, largest),
        "refill_batch_covers_largest_service",
        "refill batch covers the largest resident cohort",
        details={"refill_batch": int(dispatcher_refill_batch), "largest_target_active": largest},
    )
    _check(
        checks,
        int(dispatcher_refill_batch) >= max(1, largest_queue_depth),
        "refill_batch_covers_largest_queue_depth",
        "refill batch covers the largest resident submit queue depth",
        details={"refill_batch": int(dispatcher_refill_batch), "largest_queue_depth_target": largest_queue_depth},
    )


def _scheduler_worker_checks(
    checks: list[dict[str, Any]],
    *,
    dispatcher_cohort_workers: int,
    service_count: int,
    largest: int,
    target_sum: int,
    largest_queue_depth: int,
) -> None:
    _check(
        checks,
        int(dispatcher_cohort_workers) >= min(max(1, service_count), 4),
        "cohort_worker_sanity",
        "cohort worker pool can make progress on the active service set",
        details={"cohort_workers": int(dispatcher_cohort_workers), "service_count": service_count},
        severity="warning",
    )
    _check(
        checks,
        int(dispatcher_cohort_workers) >= max(1, largest),
        "cohort_workers_cover_largest_service",
        "cohort worker pool can feed the largest resident target without underfilling vLLM",
        details={"cohort_workers": int(dispatcher_cohort_workers), "largest_target_active": largest},
    )
    _check(
        checks,
        int(dispatcher_cohort_workers) >= max(1, largest_queue_depth),
        "cohort_workers_cover_largest_queue_depth",
        "cohort worker pool can feed the largest resident submit queue depth",
        details={"cohort_workers": int(dispatcher_cohort_workers), "largest_queue_depth_target": largest_queue_depth},
    )
    _check(
        checks,
        int(dispatcher_cohort_workers) >= target_sum,
        "cohort_workers_cover_sum_targets",
        "cohort worker pool can feed every active resident target at once",
        details={"cohort_workers": int(dispatcher_cohort_workers), "target_active_sum": target_sum},
        severity="warning",
    )


def _readiness_payload(
    *,
    checks: list[dict[str, Any]],
    strict: bool,
    services: list[Any],
    targets: dict[str, int],
    queue_depth_targets: dict[str, int],
    target_sum: int,
    largest: int,
    queue_depth_sum: int,
    largest_queue_depth: int,
    dispatcher_window: int,
    dispatcher_refill_batch: int,
    dispatcher_cohort_workers: int,
    gpu_budget: dict[str, float],
) -> dict[str, Any]:
    errors = [item for item in checks if item["severity"] == "error" and not item["ok"]]
    warnings = [item for item in checks if item["severity"] == "warning" and not item["ok"]]
    return {
        "format": READINESS_FORMAT,
        "ready": not errors,
        "strict": strict,
        "active_resident_service_ids": [service.service_id for service in services],
        "resident_service_targets": targets,
        "resident_service_queue_depth_targets": queue_depth_targets,
        "target_active_sum": target_sum,
        "largest_target_active": largest,
        "queue_depth_target_sum": queue_depth_sum,
        "largest_queue_depth_target": largest_queue_depth,
        "dispatcher_window": int(dispatcher_window),
        "dispatcher_refill_batch": int(dispatcher_refill_batch),
        "dispatcher_cohort_workers": int(dispatcher_cohort_workers),
        "resident_gpu_memory_utilization": gpu_budget,
        "resident_gpu_memory_utilization_sum": round(sum(gpu_budget.values()), 6),
        "resident_kv_backends": {service.service_id: str(service.kv_cache.get("external_backend") or "") for service in services},
        "resident_kv_connectors": {service.service_id: str(service.kv_cache.get("connector_id") or "") for service in services},
        "hard_error_count": len(errors),
        "warning_count": len(warnings),
        "checks": checks,
    }


def default_dispatch_window(topology: SparkTopology) -> int:
    services = _active_services(topology, active_resident_service_ids(topology))
    values = [_service_queue_depth_target(service) for service in services]
    return max(64, sum(values) if values else 0)


def default_cohort_workers(topology: SparkTopology) -> int:
    services = _active_services(topology, active_resident_service_ids(topology))
    values = [_service_queue_depth_target(service) for service in services]
    return max(4, sum(values) if values else 0)


def _active_services(topology: SparkTopology, active_ids: set[str] | None) -> list[Any]:
    services = []
    for service in topology.pipeline_services.values():
        if active_ids is not None and service.service_id not in active_ids:
            continue
        services.append(service)
    return services


def _service_queue_depth_target(service: Any) -> int:
    target = service_target_active(service)
    scheduler = getattr(service, "scheduler", {}) or {}
    if isinstance(scheduler, dict):
        for key in ("queue_depth_target", "vllm_queue_depth_target", "submit_queue_depth_target"):
            value = scheduler.get(key)
            if value is not None:
                return max(target, int(value))
    return target


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


def _external_kv_checks(checks: list[dict[str, Any]], *, services: list[Any]) -> None:
    for service in services:
        _external_kv_service_checks(checks, service)
    _external_kv_auto_plan_checks(checks, services=services)


def _external_kv_service_checks(checks: list[dict[str, Any]], service: Any) -> None:
    kv_cache = dict(getattr(service, "kv_cache", {}) or {})
    connector_id = str(kv_cache.get("connector_id") or "")
    cache_root = str(kv_cache.get("cache_root") or kv_cache.get("storage_root") or "")
    backend = str(kv_cache.get("external_backend") or "")
    _external_kv_root_connector_checks(checks, service, cache_root, connector_id)
    _external_kv_backend_checks(checks, service, backend, connector_id)
    _external_kv_sharding_checks(checks, service, kv_cache)


def _external_kv_root_connector_checks(
    checks: list[dict[str, Any]], service: Any, cache_root: str, connector_id: str
) -> None:
    _check(
        checks,
        bool(cache_root),
        f"{service.service_id}:external_kv_cache_root",
        "active resident service declares a node-local external KV cache root",
        details={"cache_root": cache_root},
    )
    _check(
        checks,
        bool(connector_id) and connector_id != "none",
        f"{service.service_id}:external_kv_connector_present",
        "active resident service declares a non-cold external KV connector",
        details={"connector_id": connector_id},
    )


def _external_kv_backend_checks(
    checks: list[dict[str, Any]], service: Any, backend: str, connector_id: str
) -> None:
    expected_connector = FIRST3_CACHE_CONNECTORS.get(service.service_id)
    expected_backend = FIRST3_CACHE_BACKENDS.get(service.service_id)
    if expected_connector is not None:
        _check(
            checks,
            connector_id == expected_connector,
            f"{service.service_id}:external_kv_connector_expected",
            "active resident service uses the expected first-three external KV connector",
            details={"expected": expected_connector, "actual": connector_id},
        )
    if expected_backend is not None:
        _check(
            checks,
            backend == expected_backend,
            f"{service.service_id}:external_kv_backend_expected",
            "active resident service uses the expected first-three external KV backend",
            details={"expected": expected_backend, "actual": backend},
        )


def _external_kv_sharding_checks(checks: list[dict[str, Any]], service: Any, kv_cache: dict[str, Any]) -> None:
    expected_fraction = 1.0 / max(1, len(service.node_ids))
    actual_fraction = _float_or_none(kv_cache.get("expected_entry_fraction_per_node"))
    _check(
        checks,
        str(kv_cache.get("sharding", "")) == "pipeline_layers",
        f"{service.service_id}:external_kv_pipeline_sharded",
        "external KV entries are sharded by pipeline stage",
        details={"sharding": kv_cache.get("sharding")},
    )
    _check(
        checks,
        actual_fraction is not None and abs(actual_fraction - expected_fraction) < 0.000001,
        f"{service.service_id}:external_kv_node_fraction",
        "external KV node fraction matches the pipeline width",
        details={"expected": expected_fraction, "actual": actual_fraction},
    )


def _external_kv_auto_plan_checks(checks: list[dict[str, Any]], *, services: list[Any]) -> None:
    cached_services = _services_with_external_kv(services)
    if not cached_services:
        return
    auto_enabled = _env_bool("DS4_PIPELINE_AUTO_KV_CACHE", False)
    allowed = _csv_env("DS4_PIPELINE_AUTO_KV_CACHE_SERVICE_IDS")
    missing = sorted(service.service_id for service in cached_services if allowed and service.service_id not in allowed and service.profile_id not in allowed)
    _check(
        checks,
        auto_enabled,
        "external_kv_auto_plan_enabled",
        "DSAPI auto-KV plans are enabled for resident external KV services",
        details={"services": [service.service_id for service in cached_services], "DS4_PIPELINE_AUTO_KV_CACHE": os.environ.get("DS4_PIPELINE_AUTO_KV_CACHE", "")},
    )
    _check(
        checks,
        not missing,
        "external_kv_auto_plan_service_ids_cover_active",
        "DSAPI auto-KV service allowlist covers every active external KV service",
        details={"missing": missing, "allowed": sorted(allowed)},
    )


def _resident_gpu_budget_checks(checks: list[dict[str, Any]], *, services: list[Any], gpu_budget: dict[str, float]) -> None:
    missing = [service.service_id for service in services if service.service_id not in gpu_budget]
    _check(
        checks,
        not missing,
        "resident_gpu_budget_declared",
        "active resident services declare GPU memory utilization caps",
        details={"missing": missing, "budget": gpu_budget},
    )
    total = sum(gpu_budget.values())
    _check(
        checks,
        total <= FIRST3_GPU_UTILIZATION_HARD_CAP,
        "first3_gpu_budget_under_hard_cap",
        "first-three resident GPU memory utilization leaves deployment headroom",
        details={"sum": round(total, 6), "hard_cap": FIRST3_GPU_UTILIZATION_HARD_CAP},
    )
    for service in services:
        value = gpu_budget.get(service.service_id)
        floor = FIRST3_GPU_UTILIZATION_FLOORS.get(service.service_id)
        if value is None or floor is None:
            continue
        _check(
            checks,
            value >= floor,
            f"{service.service_id}:gpu_budget_not_starved",
            "GPU memory utilization cap is not below the known first-three service floor",
            details={"value": value, "floor": floor},
            severity="warning",
        )
    dsv4 = gpu_budget.get("dsv4_flash_pp8")
    if dsv4 is not None:
        _check(
            checks,
            dsv4 < 0.33,
            "dsv4_gpu_budget_below_no_headroom_startup_point",
            "DSV4 GPU cap stays below the observed co-resident no-headroom startup failure point",
            details={"value": dsv4, "failed_startup_point": 0.33},
        )


def _gpu_budget_by_service(services: list[Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for service in services:
        value = _float_or_none(dict(getattr(service, "kv_cache", {}) or {}).get("gpu_memory_utilization"))
        if value is not None:
            out[service.service_id] = value
    return out


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _jit_kv_checks(checks: list[dict[str, Any]], *, services: list[Any], strict: bool) -> None:
    token = os.environ.get("DS4_API_JIT_KV_PREFETCH_TOKEN", "")
    endpoint_enabled = _env_bool("DS4_API_JIT_KV_PREFETCH_API", bool(token))
    needs_prefetch = _services_need_jit_prefetch(services)
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
        (not needs_prefetch) or endpoint_enabled,
        "jit_kv_prefetch_gate_enabled",
        "vLLM DS4 KV prefetch endpoint use is enabled",
        details={"required": needs_prefetch},
        severity="error" if strict or needs_prefetch else "warning",
    )
    _check(
        checks,
        (not needs_prefetch) or bool(token),
        "jit_kv_prefetch_token_present",
        "DS4 has a token for vLLM DS4 KV prefetch",
        details={"required": needs_prefetch},
        severity="error" if strict or needs_prefetch else "warning",
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


def _services_with_external_kv(services: list[Any]) -> list[Any]:
    out = []
    for service in services:
        kv_cache = dict(getattr(service, "kv_cache", {}) or {})
        connector = str(kv_cache.get("connector_id") or "")
        backend = str(kv_cache.get("external_backend") or "")
        if connector and connector != "none" and backend and backend != "none":
            out.append(service)
    return out


def _services_need_jit_prefetch(services: list[Any]) -> bool:
    for service in services:
        kv_cache = dict(getattr(service, "kv_cache", {}) or {})
        backend = str(kv_cache.get("external_backend") or "")
        connector = str(kv_cache.get("connector_id") or "")
        if backend == "dsv4_hma" or connector == "simple_cpu_offload":
            return True
    return False


def _csv_env(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    return {item.strip() for item in raw.replace(";", ",").split(",") if item.strip()}


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
