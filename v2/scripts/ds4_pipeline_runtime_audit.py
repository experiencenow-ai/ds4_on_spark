#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIRST3_EXTERNAL_CACHE = {
    "qwen27_bf16_pp8": {
        "external_backend": "lmcache_hma",
        "connector_id": "lmcache",
        "cache_root": "/home/{node}/ds4_nvme/ds4_lmcache/qwen27_bf16_pp8_fp8kv",
        "gpu_memory_utilization": "0.25",
        "env_root": "LMCACHE_ROOT",
    },
    "gemma4_26b_a4b_pp8": {
        "external_backend": "lmcache_hma",
        "connector_id": "lmcache",
        "cache_root": "/home/{node}/ds4_nvme/ds4_lmcache/gemma4_26b_a4b_pp8_bf16kv",
        "gpu_memory_utilization": "0.25",
        "env_root": "LMCACHE_ROOT",
    },
    "dsv4_flash_pp8": {
        "external_backend": "dsv4_hma",
        "connector_id": "simple_cpu_offload",
        "cache_root": "/home/{node}/ds4_nvme/ds4_hma_store/dsv4_flash_pp8/simple_cpu_offload",
        "gpu_memory_utilization": "0.28",
        "env_root": "VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT",
    },
}
DSV4_PRODUCTION_PROFILE = ROOT / "profiles" / "production" / "dsv4_flash_pp8_resident128.json"


def main() -> int:
    errors: list[str] = []
    checks: list[str] = []
    dsv4_profile = _load(DSV4_PRODUCTION_PROFILE)
    topology = _load(ROOT / "profiles" / "topology" / "static_sparks.json")
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing["pipeline_services"]
    service_id = str(dsv4_profile["service_id"])
    _check_dsv4(dsv4_profile, services[service_id], errors, checks)
    _check_qwen(errors, checks)
    _check_gemma_co_residency(errors, checks)
    _check_first3_external_cache_contract(topology, errors, checks)
    _check_relaunch_defaults(dsv4_profile, errors, checks)
    _check_spark_update_scripts(errors, checks)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    for check in checks:
        print(f"PASS: {check}")
    return 0


def _check_dsv4(profile: dict[str, Any], service: dict[str, Any], errors: list[str], checks: list[str]) -> None:
    contract = _load(ROOT / str(profile["runtime_contract"]))
    deployment = _load(ROOT / str(profile["kv_deployment"]))
    scheduler = service.get("scheduler") if isinstance(service.get("scheduler"), dict) else {}
    layer_partition = _as_int_list(profile["layer_partition"])
    compilation_config = json.dumps(profile["compilation_config"], separators=(",", ":"))
    for name, args in (("runtime contract", contract["launch"]["args"]), ("KV deployment", _effective_launch_args(deployment))):
        _require_arg(args, "--max-model-len", str(profile["max_model_len"]), f"DSV4 {name} max model len", errors, checks)
        _require_arg(args, "--max-num-seqs", str(profile["max_num_seqs"]), f"DSV4 {name} max seqs", errors, checks)
        _require_arg(args, "--max-num-batched-tokens", str(profile["max_num_batched_tokens"]), f"DSV4 {name} token budget", errors, checks)
        _require_arg(args, "--kv-cache-memory-bytes", str(profile["kv_cache_memory_bytes"]), f"DSV4 {name} bounded resident KV bytes", errors, checks)
        _require_arg(args, "--gpu-memory-utilization", str(profile["gpu_memory_utilization"]), f"DSV4 {name} bounded GPU memory utilization", errors, checks)
        _require_arg(args, "--kv-cache-dtype", str(profile["kv_cache_dtype"]), f"DSV4 {name} KV dtype", errors, checks)
        _require_arg(args, "--linear-backend", "auto", f"DSV4 {name} native linear backend auto", errors, checks)
        _require_arg(args, "--moe-backend", "auto", f"DSV4 {name} native MoE backend auto", errors, checks)
        _require_arg(args, "--compilation-config", compilation_config, f"DSV4 {name} compilation config", errors, checks)
        if "--speculative-config" in [str(item) for item in args]:
            errors.append(f"DSV4 {name}: resident production must not enable MTP/speculative decode")
        else:
            checks.append(f"DSV4 {name} keeps MTP/speculative decode off")
    _require_arg(contract["launch"]["args"], "--pipeline-parallel-size", str(profile["pipeline_parallel_size"]), "DSV4 runtime contract PP size", errors, checks)
    _require_arg(contract["launch"]["args"], "--tensor-parallel-size", str(profile["tensor_parallel_size"]), "DSV4 runtime contract TP size", errors, checks)
    _require_equal(contract["pipeline"].get("pipeline_parallel_size"), profile["pipeline_parallel_size"], "DSV4 runtime pipeline PP size", errors, checks)
    _require_equal(contract["pipeline"].get("tensor_parallel_size"), profile["tensor_parallel_size"], "DSV4 runtime pipeline TP size", errors, checks)
    _require_equal(deployment.get("pipeline_parallel_size"), profile["pipeline_parallel_size"], "DSV4 KV deployment PP size", errors, checks)
    _require_equal(deployment.get("tensor_parallel_size"), profile["tensor_parallel_size"], "DSV4 KV deployment TP size", errors, checks)
    _require_equal(contract["model"].get("model_id"), "/home/{node}/models/hf/deepseek-ai/DeepSeek-V4-Flash", "DSV4 runtime contract node-local model path", errors, checks)
    _require_equal(deployment.get("model_id"), "/home/{node}/models/hf/deepseek-ai/DeepSeek-V4-Flash", "DSV4 KV deployment node-local model path", errors, checks)
    _require_equal(service.get("model_id"), "/home/{node}/models/hf/deepseek-ai/DeepSeek-V4-Flash", "DSV4 topology node-local model path", errors, checks)
    _require_equal(deployment.get("fabric_topology"), "../transfer/spark_200g.json", "DSV4 KV deployment static 200G fabric topology", errors, checks)
    _require_equal(service.get("layer_partition"), layer_partition, "DSV4 topology source-owned PP8 partition", errors, checks)
    _require_equal(contract["pipeline"].get("layer_partition"), layer_partition, "DSV4 runtime partition", errors, checks)
    _require_equal(deployment.get("layer_partition"), layer_partition, "DSV4 KV deployment partition", errors, checks)
    _require_equal(service.get("max_batch_size"), profile["max_batch_size"], "DSV4 topology max batch size", errors, checks)
    for actual_key, profile_key in {
        "queue_concurrency": "queue_concurrency",
        "queue_limit": "queue_limit",
        "refill_low_watermark": "refill_low_watermark",
        "max_running_batches_per_compute_domain": "max_running_batches_per_compute_domain",
        "vllm_max_num_batched_tokens": "max_num_batched_tokens",
        "vllm_max_num_seqs": "max_num_seqs",
    }.items():
        _require_equal(_scheduler_value(service, scheduler, actual_key), profile[profile_key], f"DSV4 topology scheduler {actual_key}", errors, checks)
    env = deployment.get("extra_env") if isinstance(deployment.get("extra_env"), dict) else {}
    _check_dsv4_env(profile, env, errors, checks)


def _check_dsv4_env(profile: dict[str, Any], env: dict[str, Any], errors: list[str], checks: list[str]) -> None:
    expected = {
        "GLOO_SOCKET_IFNAME": "ds4ring0",
        "CPATH": "/home/{node}/standard-runtimes/python3.12-dev-extract/usr/include:/home/{node}/standard-runtimes/python3.12-dev-extract/usr/include/python3.12:/home/{node}/standard-runtimes/python3.12-dev-extract/usr/include/aarch64-linux-gnu/python3.12",
        "PATH": "/home/{node}/ds4-vllm-local/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "TP_SOCKET_IFNAME": "ds4ring0",
        "VLLM_HOST_IP": "{fabric_ip}",
        "DS4_PP_TRANSPORT": str(profile["pp_transport"]),
        "VLLM_DS4_PP_EDGE_RAIL": str(profile["pp_edge_rail"]),
        "VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR": "1",
        "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT": "0",
        "VLLM_DS4_PP_TCP_TENSOR_DICT": "1",
        "VLLM_DS4_PP_TCP_STRIPES": "16",
        "VLLM_DS4_PP_TCP_MIN_BYTES": "1",
        "VLLM_DS4_PP_TCP_BIND_HOST": "{fabric_ip}",
        "VLLM_DS4_PP_TCP_ADVERTISE_HOST": "{fabric_ip}",
        "VLLM_DS4_PP_DEVICE_TENSOR_DICT_METADATA": "0",
        "VLLM_DS4_PP_PYNCCL_TENSOR_DICT": "0",
        "VLLM_DS4_PP_PYNCCL_PAIR_COMMUNICATORS": "0",
        "VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT": "0",
        "VLLM_DS4_PP_TORCH_PG_TENSOR_DICT": "0",
        "VLLM_DS4_PP_TORCH_PAIR_GROUPS": "0",
        "VLLM_DS4_PP_TORCH_GROUP_WARMUP": "0",
        "VLLM_DS4_PP_OVERLAP_SEND": "1",
        "VLLM_DS4_SCHED_MAX_NEW_REQS_PER_STEP": "64",
        "VLLM_DS4_FINAL_ONLY_NONSTREAMING": "1",
    }
    for key, value in expected.items():
        _require_equal(env.get(key), value, f"DSV4 env {key}", errors, checks)


def _check_qwen(errors: list[str], checks: list[str]) -> None:
    qwen_launches = {
        "profiles/runtime_contracts/qwen27_bf16_pp8_v1.json": ("fp8", "0.25"),
        "profiles/runtime_contracts/qwen27_bf16_pp8_bf16kv_v1.json": ("auto", "0.35"),
        "profiles/runtime_contracts/qwen27_vllm_trim_v1.json": ("fp8", ""),
        "profiles/kv_cache/qwen27_bf16_pp8_lmcache_hma.json": ("fp8", "0.25"),
        "profiles/kv_cache/qwen27_bf16_pp8_bf16kv_lmcache_hma.json": ("auto", "0.35"),
        "profiles/kv_cache/qwen27_lmcache_mp_spark7.json": ("fp8", ""),
    }
    for rel, (expected_kv_dtype, expected_gpu_cap) in qwen_launches.items():
        path = ROOT / rel
        data = _load(path)
        args = data.get("extra_args") if isinstance(data.get("extra_args"), list) else data.get("launch", {}).get("args", [])
        _require_arg(args, "--kv-cache-dtype", expected_kv_dtype, f"{rel} explicit Qwen KV dtype", errors, checks)
        _require_arg(args, "--attention-backend", "TRITON_ATTN", f"{rel} Triton attention", errors, checks)
        if expected_gpu_cap:
            _require_arg(args, "--gpu-memory-utilization", expected_gpu_cap, f"{rel} co-resident GPU memory cap", errors, checks)
        if "--async-scheduling" in args:
            errors.append(f"{rel}: Qwen production launch must not enable vLLM async scheduling")
        else:
            checks.append(f"{rel} does not enable vLLM async scheduling")
    _check_qwen_pp8_deployment(
        "profiles/kv_cache/qwen27_bf16_pp8_lmcache_hma.json",
        "Qwen BF16 FP8-KV PP8",
        "fp8kv",
        errors,
        checks,
    )
    _check_qwen_pp8_deployment(
        "profiles/kv_cache/qwen27_bf16_pp8_bf16kv_lmcache_hma.json",
        "Qwen BF16 BF16-KV PP8",
        "bf16kv",
        errors,
        checks,
    )


def _check_qwen_pp8_deployment(rel: str, label: str, root_marker: str, errors: list[str], checks: list[str]) -> None:
    deployment = _load(ROOT / rel)
    _require_equal(deployment.get("model_id"), "/home/{node}/models/hf/Qwen/Qwen3.6-27B", f"{label} launch uses node-local model path", errors, checks)
    _require_equal(deployment.get("fabric_topology"), "../transfer/spark_200g.json", f"{label} launch uses static 200G fabric topology", errors, checks)
    env = deployment.get("extra_env") if isinstance(deployment.get("extra_env"), dict) else {}
    _check_qwen_pp8_env(env, errors, checks)
    root = str(env.get("LMCACHE_ROOT") or "")
    if root_marker not in root:
        errors.append(f"{label} LMCache root must be {root_marker} namespaced")
    else:
        checks.append(f"{label} LMCache root is {root_marker} namespaced")
    config = deployment.get("lmcache_config") if isinstance(deployment.get("lmcache_config"), dict) else {}
    _require_equal(config.get("local_disk"), root, f"{label} LMCache config uses the declared root", errors, checks)
    _require_equal(config.get("chunk_size"), 256, f"{label} LMCache config chunk size", errors, checks)
    _require_equal(config.get("local_cpu"), True, f"{label} LMCache config enables local CPU buffer", errors, checks)
    _require_equal(config.get("save_unfull_chunk"), False, f"{label} LMCache config keeps partial chunks off", errors, checks)


def _check_qwen_pp8_env(env: dict[str, Any], errors: list[str], checks: list[str]) -> None:
    for key, value in {
        "CPATH": "/home/{node}/standard-runtimes/python3.12-dev-extract/usr/include:/home/{node}/standard-runtimes/python3.12-dev-extract/usr/include/python3.12:/home/{node}/standard-runtimes/python3.12-dev-extract/usr/include/aarch64-linux-gnu/python3.12",
        "PATH": "/home/{node}/ds4-vllm-local/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "GLOO_SOCKET_IFNAME": "ds4ring0",
        "TP_SOCKET_IFNAME": "ds4ring0",
        "VLLM_HOST_IP": "{fabric_ip}",
        "DS4_PP_TRANSPORT": "tcp-staged",
        "VLLM_DS4_PP_EDGE_RAIL": "enp",
        "VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR": "1",
        "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT": "0",
        "VLLM_DS4_PP_TCP_TENSOR_DICT": "1",
        "VLLM_DS4_PP_TCP_STRIPES": "16",
        "VLLM_DS4_PP_TCP_MIN_BYTES": "1",
        "VLLM_DS4_PP_TCP_BIND_HOST": "{fabric_ip}",
        "VLLM_DS4_PP_TCP_ADVERTISE_HOST": "{fabric_ip}",
        "VLLM_DS4_PP_DEVICE_TENSOR_DICT_METADATA": "0",
        "VLLM_DS4_PP_PYNCCL_TENSOR_DICT": "0",
        "VLLM_DS4_PP_PYNCCL_PAIR_COMMUNICATORS": "0",
        "VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT": "0",
        "VLLM_DS4_PP_TORCH_PG_TENSOR_DICT": "0",
        "VLLM_DS4_PP_TORCH_PAIR_GROUPS": "0",
        "VLLM_DS4_PP_TORCH_GROUP_WARMUP": "0",
    }.items():
        _require_equal(env.get(key), value, f"Qwen BF16 PP8 env {key}", errors, checks)


def _check_gemma_co_residency(errors: list[str], checks: list[str]) -> None:
    for path in sorted((ROOT / "profiles" / "kv_cache").glob("gemma4_*_pp8_plain.json")):
        data = _load(path)
        args = data.get("extra_args") if isinstance(data.get("extra_args"), list) else []
        expected_cap = "0.20" if path.name.startswith("gemma4_31b_") else "0.25"
        _require_arg(args, "--gpu-memory-utilization", expected_cap, f"{path.name} co-resident GPU memory cap", errors, checks)
        if "--disable-hybrid-kv-cache-manager" not in [str(item) for item in args]:
            errors.append(f"{path.name}: Gemma PP8 must disable hybrid KV cache manager")
        else:
            checks.append(f"{path.name} disables hybrid KV cache manager")
    for path in sorted((ROOT / "profiles" / "runtime_contracts").glob("gemma4_*_pp8_v1.json")):
        data = _load(path)
        launch = data.get("launch") if isinstance(data.get("launch"), dict) else {}
        args = launch.get("args") if isinstance(launch.get("args"), list) else []
        expected_cap = "0.20" if path.name.startswith("gemma4_31b_") else "0.25"
        _require_arg(args, "--gpu-memory-utilization", expected_cap, f"{path.name} co-resident GPU memory cap", errors, checks)


def _check_first3_external_cache_contract(topology: dict[str, Any], errors: list[str], checks: list[str]) -> None:
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing.get("pipeline_services") if isinstance(routing.get("pipeline_services"), dict) else {}
    active = set(str(item) for item in routing.get("active_resident_service_ids", []))
    _require_equal(active, set(FIRST3_EXTERNAL_CACHE), "first-three active service set", errors, checks)
    for service_id, spec in FIRST3_EXTERNAL_CACHE.items():
        service = services.get(service_id) if isinstance(services.get(service_id), dict) else {}
        _check_first3_topology_cache(service_id, service, spec, errors, checks)
        _check_first3_deployment_cache(service_id, service, spec, errors, checks)
    _check_first3_gpu_sum(errors, checks)


def _check_first3_topology_cache(
    service_id: str, service: dict[str, Any], spec: dict[str, str], errors: list[str], checks: list[str]
) -> None:
    kv_cache = service.get("kv_cache") if isinstance(service.get("kv_cache"), dict) else {}
    _require_equal(kv_cache.get("external_backend"), spec["external_backend"], f"{service_id} semantic external KV backend", errors, checks)
    _require_equal(kv_cache.get("connector_id"), spec["connector_id"], f"{service_id} concrete external KV connector id", errors, checks)
    _require_equal(kv_cache.get("cache_root"), spec["cache_root"], f"{service_id} topology cache root", errors, checks)
    _require_equal(str(kv_cache.get("gpu_memory_utilization")), spec["gpu_memory_utilization"], f"{service_id} topology GPU memory cap", errors, checks)


def _check_first3_deployment_cache(
    service_id: str, service: dict[str, Any], spec: dict[str, str], errors: list[str], checks: list[str]
) -> None:
    deployment = _first3_deployment_for_service(service_id, service, errors)
    if deployment is None:
        return
    connector = deployment.get("connector") if isinstance(deployment.get("connector"), dict) else {}
    env = deployment.get("extra_env") if isinstance(deployment.get("extra_env"), dict) else {}
    args = _effective_launch_args(deployment)
    _require_equal(deployment.get("external_backend"), spec["external_backend"], f"{service_id} deployment semantic external KV backend", errors, checks)
    _require_equal(connector.get("connector_id"), spec["connector_id"], f"{service_id} deployment connector id", errors, checks)
    _require_equal(_first_cache_directory(deployment), spec["cache_root"], f"{service_id} deployment cache root", errors, checks)
    _require_equal(env.get(str(spec["env_root"])), spec["cache_root"], f"{service_id} deployment env cache root", errors, checks)
    _require_arg(args, "--gpu-memory-utilization", spec["gpu_memory_utilization"], f"{service_id} deployment GPU memory cap", errors, checks)
    if service_id == "dsv4_flash_pp8":
        _check_dsv4_hma_connector(connector, env, errors, checks)


def _first3_deployment_for_service(service_id: str, service: dict[str, Any], errors: list[str]) -> dict[str, Any] | None:
    profile = _profile_by_id(str(service.get("profile_id")))
    routing = profile.get("routing") if isinstance(profile.get("routing"), dict) else {}
    deployments = routing.get("optional_kv_cache_deployments", [])
    if len(deployments) != 1:
        errors.append(f"{service_id}: expected exactly one optional KV deployment")
        return None
    return _load(ROOT / str(deployments[0]))


def _check_dsv4_hma_connector(connector: dict[str, Any], env: dict[str, Any], errors: list[str], checks: list[str]) -> None:
    extra = connector.get("kv_connector_extra_config") if isinstance(connector.get("kv_connector_extra_config"), dict) else {}
    _require_equal(extra.get("spec_name"), "SimpleCPUOffloadingSpec", "Dsv4 HMA SimpleCPUOffload spec", errors, checks)
    _require_equal(env.get("VLLM_USE_SIMPLE_KV_OFFLOAD"), "1", "Dsv4 HMA simple offload runtime enabled", errors, checks)


def _check_first3_gpu_sum(errors: list[str], checks: list[str]) -> None:
    gpu_sum = sum(float(spec["gpu_memory_utilization"]) for spec in FIRST3_EXTERNAL_CACHE.values())
    if gpu_sum > 0.85:
        errors.append(f"first-three GPU memory cap sum {gpu_sum:.2f} exceeds 0.85")
    else:
        checks.append("first-three GPU memory cap sum leaves deployment headroom")


def _check_relaunch_defaults(profile: dict[str, Any], errors: list[str], checks: list[str]) -> None:
    module = _load_module(ROOT / "scripts" / "ds4_relaunch_coordinator_api.py")
    defaults = module._profile_defaults(str(profile["coordinator_profile"]))
    coordinator = profile["coordinator"]
    topology = _load(ROOT / "profiles" / "topology" / "static_sparks.json")
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing.get("pipeline_services") if isinstance(routing.get("pipeline_services"), dict) else {}
    for key, profile_key in {
        "DS4_API_DISPATCH_WINDOW": "dispatch_window",
        "DS4_API_DISPATCH_REFILL_BATCH": "dispatch_refill_batch",
        "DS4_PIPELINE_COMPLETION_COHORT_MAX": "completion_cohort_max",
        "DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": "completion_token_budget",
        "DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": "completion_pp_safe_cohort_max",
        "DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY": "completion_chunk_concurrency",
        "DS4_API_DISPATCH_KV_CAPACITY_BYTES": "dispatch_kv_capacity_bytes",
    }.items():
        _require_equal(defaults.get(key), str(coordinator[profile_key]), f"coordinator {profile['coordinator_profile']} {key}", errors, checks)
    batch_limits = json.loads(defaults.get("DS4_API_BATCH_LIMITS_JSON", "{}"))
    _require_equal(batch_limits.get(str(profile["service_id"])), profile["max_num_seqs"], f"coordinator {profile['coordinator_profile']} DSV4 batch limit", errors, checks)
    _require_equal(set(batch_limits), set(services), f"coordinator {profile['coordinator_profile']} topology batch-limit services", errors, checks)
    for service_id, service in services.items():
        if not isinstance(service, dict):
            continue
        scheduler = service.get("scheduler") if isinstance(service.get("scheduler"), dict) else {}
        expected = int(scheduler.get("vllm_max_num_seqs") or service.get("max_batch_size") or 0)
        _require_equal(batch_limits.get(str(service_id)), expected, f"coordinator {profile['coordinator_profile']} {service_id} vLLM batch limit", errors, checks)
    if "DS4_API_DISPATCH_KV_CAPACITY_BYTES" not in module._SAFETY_PROFILE_DEFAULTS:
        errors.append("coordinator relaunch must override unsafe inherited KV admission env")
    else:
        checks.append("coordinator relaunch overrides unsafe inherited KV admission env")


def _scheduler_value(service: dict[str, Any], scheduler: dict[str, Any], key: str) -> Any:
    if key in scheduler:
        return scheduler[key]
    if key in {"queue_concurrency", "queue_limit", "vllm_max_num_seqs"}:
        return service.get("max_batch_size")
    return None


def _profile_by_id(profile_id: str) -> dict[str, Any]:
    for path in sorted((ROOT / "profiles" / "models").glob("*.json")):
        data = _load(path)
        if str(data.get("profile_id")) == profile_id:
            return data
    raise ValueError(f"unknown profile id: {profile_id}")


def _first_cache_directory(deployment: dict[str, Any]) -> str:
    directories = deployment.get("cache_directories")
    if isinstance(directories, list) and directories:
        return str(directories[0])
    return ""


def _check_spark_update_scripts(errors: list[str], checks: list[str]) -> None:
    update_script = (ROOT.parent / "scripts" / "ds4_update_spark_nodes.sh").read_text(encoding="utf-8")
    pull_script = (ROOT.parent / "scripts" / "ds4_pull_spark_nodes.sh").read_text(encoding="utf-8")
    required = {
        "update_mode=\"${DS4_UPDATE_MODE:-code-only}\"": "Spark updater defaults to code-only mode",
        "default_self_update=0": "Spark updater code-only avoids local self-update",
        "default_configure_qwen_runtime=0": "Spark updater code-only avoids Qwen runtime edits",
        "default_install_dsv4_local=0": "Spark updater code-only avoids DSV4 unit installs",
    }
    for needle, label in required.items():
        if needle not in update_script:
            errors.append(label)
        else:
            checks.append(label)
    default_nodes = "nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)"
    self_update_call = "self_update_local_checkout \"${nodes[@]}\""
    if default_nodes not in update_script:
        errors.append("Spark updater must default no-arg runs to spark0..spark7")
    elif update_script.find(default_nodes) > update_script.find(self_update_call):
        errors.append("Spark updater must set default nodes before self-update expansion")
    else:
        checks.append("Spark updater no-arg default nodes are set before self-update")
    if "--code-only" not in pull_script or "ds4_update_spark_nodes.sh" not in pull_script:
        errors.append("Spark pull wrapper must call ds4_update_spark_nodes.sh --code-only")
    else:
        checks.append("Spark pull wrapper calls updater in code-only mode")


def _effective_launch_args(data: dict[str, Any]) -> list[Any]:
    args = list(data.get("extra_args") if isinstance(data.get("extra_args"), list) else data.get("launch", {}).get("args", []))
    if data.get("max_batch_size") is not None and "--max-num-seqs" not in [str(item) for item in args]:
        args.extend(["--max-num-seqs", str(data["max_batch_size"])])
    return args


def _require_arg(args: list[Any], flag: str, expected: str, label: str, errors: list[str], checks: list[str]) -> None:
    values = [str(item) for item in args]
    if flag not in values:
        errors.append(f"{label}: missing {flag}")
        return
    index = values.index(flag)
    actual = values[index + 1] if index + 1 < len(values) else ""
    if actual != str(expected):
        errors.append(f"{label}: {flag} is {actual!r}, expected {expected!r}")
        return
    checks.append(label)


def _require_equal(actual: Any, expected: Any, label: str, errors: list[str], checks: list[str]) -> None:
    if actual != expected:
        errors.append(f"{label}: {actual!r} != {expected!r}")
        return
    checks.append(label)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _as_int_list(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    return [int(item) for item in raw]


if __name__ == "__main__":
    raise SystemExit(main())
