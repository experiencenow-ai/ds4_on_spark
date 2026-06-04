#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    checks: list[str] = []
    topology = _load(ROOT / "profiles" / "topology" / "static_sparks.json")
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing["pipeline_services"]
    _check_dsv4(services["dsv4_flash_pp8"], errors, checks)
    _check_qwen(errors, checks)
    _check_relaunch_defaults(errors, checks)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    for check in checks:
        print(f"PASS: {check}")
    return 0


def _check_dsv4(service: dict[str, Any], errors: list[str], checks: list[str]) -> None:
    contract = _load(ROOT / "profiles" / "runtime_contracts" / "dsv4_flash_pp8_mtp_v1.json")
    deployment = _load(ROOT / "profiles" / "kv_cache" / "dsv4_flash_pp8_simple_offload.json")
    scheduler = service.get("scheduler") if isinstance(service.get("scheduler"), dict) else {}
    for name, args in (("runtime contract", contract["launch"]["args"]), ("KV deployment", deployment["extra_args"])):
        _require_arg(args, "--max-num-seqs", str(scheduler.get("vllm_max_num_seqs")), f"DSV4 {name} max seqs", errors, checks)
        _require_arg(args, "--max-num-batched-tokens", str(scheduler.get("vllm_max_num_batched_tokens")), f"DSV4 {name} token budget", errors, checks)
        _require_arg(args, "--kv-cache-memory-bytes", "4294967296", f"DSV4 {name} explicit resident KV bytes", errors, checks)
        _require_arg(args, "--linear-backend", "auto", f"DSV4 {name} native linear backend auto", errors, checks)
        _require_arg(args, "--moe-backend", "auto", f"DSV4 {name} native MoE backend auto", errors, checks)
        _require_arg(args, "--compilation-config", "{\"cudagraph_mode\":\"NONE\",\"custom_ops\":[\"all\"]}", f"DSV4 {name} disables CUDA graphs for resident production", errors, checks)
        if "--speculative-config" in [str(item) for item in args]:
            errors.append(f"DSV4 {name}: resident production must not enable MTP/speculative decode")
        else:
            checks.append(f"DSV4 {name} keeps MTP/speculative decode off")
    expected_partition = [6, 6, 6, 5, 5, 5, 5, 5]
    _require_equal(service.get("layer_partition"), expected_partition, "DSV4 topology balanced PP8 partition", errors, checks)
    _require_equal(contract["pipeline"].get("layer_partition"), expected_partition, "DSV4 runtime partition", errors, checks)
    _require_equal(deployment.get("layer_partition"), expected_partition, "DSV4 KV deployment partition", errors, checks)
    env = deployment.get("extra_env") if isinstance(deployment.get("extra_env"), dict) else {}
    for key, value in {
        "VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR": "0",
        "VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT": "1",
        "VLLM_DS4_PP_OVERLAP_SEND": "1",
        "VLLM_DS4_SCHED_MAX_NEW_REQS_PER_STEP": "64",
        "VLLM_DS4_FINAL_ONLY_NONSTREAMING": "1",
    }.items():
        _require_equal(env.get(key), value, f"DSV4 env {key}", errors, checks)


def _check_qwen(errors: list[str], checks: list[str]) -> None:
    for rel in (
        "profiles/runtime_contracts/qwen27_bf16_pp8_v1.json",
        "profiles/runtime_contracts/qwen27_vllm_trim_v1.json",
        "profiles/kv_cache/qwen27_bf16_pp8_lmcache_hma.json",
        "profiles/kv_cache/qwen27_lmcache_mp_spark7.json",
    ):
        path = ROOT / rel
        data = _load(path)
        args = data.get("extra_args") if isinstance(data.get("extra_args"), list) else data.get("launch", {}).get("args", [])
        _require_arg(args, "--kv-cache-dtype", "fp8", f"{rel} explicit FP8 KV", errors, checks)
        _require_arg(args, "--attention-backend", "TRITON_ATTN", f"{rel} Triton attention for FP8 KV", errors, checks)
        if "--async-scheduling" in args:
            errors.append(f"{rel}: Qwen production launch must not enable vLLM async scheduling")
        else:
            checks.append(f"{rel} does not enable vLLM async scheduling")
    deployment = _load(ROOT / "profiles" / "kv_cache" / "qwen27_bf16_pp8_lmcache_hma.json")
    env = deployment.get("extra_env") if isinstance(deployment.get("extra_env"), dict) else {}
    root = str(env.get("LMCACHE_ROOT") or "")
    if "fp8kv" not in root:
        errors.append("Qwen BF16 LMCache root must be FP8-KV namespaced")
    else:
        checks.append("Qwen BF16 LMCache root is FP8-KV namespaced")


def _check_relaunch_defaults(errors: list[str], checks: list[str]) -> None:
    text = (ROOT / "scripts" / "ds4_relaunch_coordinator_api.py").read_text(encoding="utf-8")
    if '"DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": "131072"' not in text:
        errors.append("coordinator throughput relaunch must use bounded 131072 token cohorts")
    else:
        checks.append("coordinator throughput relaunch uses bounded token cohorts")
    if '"DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET": "4096"' not in text:
        errors.append("coordinator production relaunch must use resident token cohorts")
    else:
        checks.append("coordinator production relaunch uses resident token cohorts")
    if '"DS4_PIPELINE_COMPLETION_PP_SAFE_COHORT_MAX": "8"' not in text:
        errors.append("coordinator production relaunch must cap PP-safe cohorts to resident DSV4 max seqs")
    else:
        checks.append("coordinator production relaunch caps PP-safe cohorts")
    if '"DS4_PIPELINE_COMPLETION_CHUNK_CONCURRENCY": "1"' not in text:
        errors.append("coordinator production relaunch must serialize resident chunks per active service")
    else:
        checks.append("coordinator production relaunch serializes resident chunks")
    if '"DS4_COMPUTE_LEASE_QUANTUM_S": "180"' not in text:
        errors.append("coordinator relaunch must set compute lease quantum")
    else:
        checks.append("coordinator relaunch sets compute lease quantum")
    if '"DS4_API_DISPATCH_KV_CAPACITY_BYTES": "51539607552"' not in text:
        errors.append("coordinator relaunch must bound dispatcher KV admission")
    else:
        checks.append("coordinator relaunch bounds dispatcher KV admission")
    if '"DS4_API_DISPATCH_KV_CAPACITY_BYTES",' not in text or "env[key] = value" not in text:
        errors.append("coordinator relaunch must override unsafe inherited KV admission env")
    else:
        checks.append("coordinator relaunch overrides unsafe inherited KV admission env")


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


if __name__ == "__main__":
    raise SystemExit(main())
