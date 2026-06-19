"""DS4 environment variable registration for upstream vLLM overlays."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from typing import Any


def _env_bool(name: str, default: str = "0") -> Callable[[], bool]:
    def _get() -> bool:
        return os.getenv(name, default).strip().lower() not in {
            "",
            "0",
            "false",
            "no",
            "off",
        }

    return _get


def _env_optional_bool(name: str) -> Callable[[], bool | None]:
    def _get() -> bool | None:
        value = os.getenv(name)
        if value is None:
            return None
        return value.strip().lower() not in {"", "0", "false", "no", "off"}

    return _get


def _env_int(name: str, default: str) -> Callable[[], int]:
    def _get() -> int:
        return int(os.getenv(name, default))

    return _get


def _env_float(name: str, default: str) -> Callable[[], float]:
    def _get() -> float:
        return float(os.getenv(name, default))

    return _get


def _env_str(name: str, default: str = "") -> Callable[[], str]:
    def _get() -> str:
        return os.getenv(name, default)

    return _get


_DS4_ENV_SPECS: dict[str, Callable[[], Any]] = {
    "VLLM_TRITON_MLA_SPARSE": _env_optional_bool("VLLM_TRITON_MLA_SPARSE"),
    "VLLM_DS4_DISABLE_DSV3_FUSED_A_GEMM": _env_bool(
        "VLLM_DS4_DISABLE_DSV3_FUSED_A_GEMM"
    ),
    "VLLM_DS4_DISABLE_DSV3_ROUTER_GEMM": _env_bool(
        "VLLM_DS4_DISABLE_DSV3_ROUTER_GEMM"
    ),
    "VLLM_DS4_DSV4_PP_FLUSH_HC_BOUNDARY": _env_bool(
        "VLLM_DS4_DSV4_PP_FLUSH_HC_BOUNDARY"
    ),
    "VLLM_DS4_DSV4_SPARSE_MLA_PREFILL_BACKEND": _env_str(
        "VLLM_DS4_DSV4_SPARSE_MLA_PREFILL_BACKEND"
    ),
    "VLLM_DS4_ENABLE_CACHE_ADMIN": _env_bool("VLLM_DS4_ENABLE_CACHE_ADMIN"),
    "VLLM_DS4_FINAL_ONLY_NONSTREAMING": _env_bool(
        "VLLM_DS4_FINAL_ONLY_NONSTREAMING"
    ),
    "VLLM_DS4_KV_PREFETCH_API": _env_bool("VLLM_DS4_KV_PREFETCH_API"),
    "VLLM_DS4_KV_PREFETCH_MAX_CONCURRENT": _env_int(
        "VLLM_DS4_KV_PREFETCH_MAX_CONCURRENT", "0"
    ),
    "VLLM_DS4_KV_PREFETCH_REQUIRE_TOKEN": _env_bool(
        "VLLM_DS4_KV_PREFETCH_REQUIRE_TOKEN"
    ),
    "VLLM_DS4_KV_PREFETCH_TOKEN": _env_str("VLLM_DS4_KV_PREFETCH_TOKEN"),
    "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT": _env_bool(
        "VLLM_DS4_PP_CPU_STAGED_TENSOR_DICT"
    ),
    "VLLM_DS4_PP_DEVICE_TENSOR_DICT_METADATA": _env_bool(
        "VLLM_DS4_PP_DEVICE_TENSOR_DICT_METADATA"
    ),
    "VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT": _env_bool(
        "VLLM_DS4_PP_DIRECT_CUDA_TENSOR_DICT"
    ),
    "VLLM_DS4_PP_DIRECT_CUDA_MIN_BYTES": _env_int(
        "VLLM_DS4_PP_DIRECT_CUDA_MIN_BYTES", "262144"
    ),
    "VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR": _env_bool(
        "VLLM_DS4_PP_DISABLE_DEVICE_COMMUNICATOR"
    ),
    "VLLM_DS4_PP_EDGE_RAIL": _env_str("VLLM_DS4_PP_EDGE_RAIL"),
    "VLLM_DS4_PP_GANTT_TRACE": _env_bool("VLLM_DS4_PP_GANTT_TRACE"),
    "VLLM_DS4_PP_GANTT_TRACE_EVERY": _env_int("VLLM_DS4_PP_GANTT_TRACE_EVERY", "1"),
    "VLLM_DS4_PP_BOUNDARY_TRACE": _env_bool("VLLM_DS4_PP_BOUNDARY_TRACE"),
    "VLLM_DS4_PP_BOUNDARY_TRACE_EVERY": _env_int(
        "VLLM_DS4_PP_BOUNDARY_TRACE_EVERY", "1"
    ),
    "VLLM_DS4_PP_BOUNDARY_TRACE_MAX_ELEMS": _env_int(
        "VLLM_DS4_PP_BOUNDARY_TRACE_MAX_ELEMS", "4096"
    ),
    "VLLM_DS4_PP_BOUNDARY_TRACE_SYNC": _env_bool(
        "VLLM_DS4_PP_BOUNDARY_TRACE_SYNC", "1"
    ),
    "VLLM_DS4_PP_NEXT_SOCKET_IFNAME": _env_str("VLLM_DS4_PP_NEXT_SOCKET_IFNAME"),
    "VLLM_DS4_PP_ONLY_GLOBAL_BACKEND": _env_str(
        "VLLM_DS4_PP_ONLY_GLOBAL_BACKEND"
    ),
    "VLLM_DS4_PP_OVERLAP_SEND": _env_bool("VLLM_DS4_PP_OVERLAP_SEND"),
    "VLLM_DS4_PP_PREV_SOCKET_IFNAME": _env_str("VLLM_DS4_PP_PREV_SOCKET_IFNAME"),
    "VLLM_DS4_PP_PYNCCL_PAIR_COMMUNICATORS": _env_bool(
        "VLLM_DS4_PP_PYNCCL_PAIR_COMMUNICATORS"
    ),
    "VLLM_DS4_PP_PYNCCL_PAIR_IFNAME_MODE": _env_str(
        "VLLM_DS4_PP_PYNCCL_PAIR_IFNAME_MODE", "process"
    ),
    "VLLM_DS4_PP_PYNCCL_P2P_CREDIT": _env_bool(
        "VLLM_DS4_PP_PYNCCL_P2P_CREDIT"
    ),
    "VLLM_DS4_PP_PYNCCL_TENSOR_DICT": _env_bool(
        "VLLM_DS4_PP_PYNCCL_TENSOR_DICT"
    ),
    "VLLM_DS4_PP_PYNCCL_TENSOR_DICT_STRIPES": _env_int(
        "VLLM_DS4_PP_PYNCCL_TENSOR_DICT_STRIPES", "1"
    ),
    "VLLM_DS4_PP_PYNCCL_TENSOR_DICT_STRIPE_MIN_BYTES": _env_int(
        "VLLM_DS4_PP_PYNCCL_TENSOR_DICT_STRIPE_MIN_BYTES", "1048576"
    ),
    "VLLM_DS4_PP_SEND_BACKLOG": _env_int("VLLM_DS4_PP_SEND_BACKLOG", "1"),
    "VLLM_DS4_PP_SEND_BUFFER_MAX_BYTES": _env_int(
        "VLLM_DS4_PP_SEND_BUFFER_MAX_BYTES", str(1024**3)
    ),
    "VLLM_DS4_PP_SEND_BUFFER_SLOTS": _env_int("VLLM_DS4_PP_SEND_BUFFER_SLOTS", "1"),
    "VLLM_DS4_PP_SOCKET_IFNAME": _env_str("VLLM_DS4_PP_SOCKET_IFNAME"),
    "VLLM_DS4_PP_STRIPED_NCCL_MIN_BYTES": _env_int(
        "VLLM_DS4_PP_STRIPED_NCCL_MIN_BYTES", "1048576"
    ),
    "VLLM_DS4_PP_STRIPED_NCCL_STREAMS": _env_bool(
        "VLLM_DS4_PP_STRIPED_NCCL_STREAMS", "1"
    ),
    "VLLM_DS4_PP_STRIPED_NCCL_STRIPES": _env_int(
        "VLLM_DS4_PP_STRIPED_NCCL_STRIPES",
        os.getenv("VLLM_DS4_PP_PYNCCL_TENSOR_DICT_STRIPES", "1"),
    ),
    "VLLM_DS4_PP_STRIPED_NCCL_TENSOR_DICT": _env_bool(
        "VLLM_DS4_PP_STRIPED_NCCL_TENSOR_DICT"
    ),
    "VLLM_DS4_PP_TCP_ADVERTISE_HOST": _env_str("VLLM_DS4_PP_TCP_ADVERTISE_HOST"),
    "VLLM_DS4_PP_TCP_BIND_HOST": _env_str("VLLM_DS4_PP_TCP_BIND_HOST"),
    "VLLM_DS4_PP_TCP_CONNECT_TIMEOUT_SECONDS": _env_float(
        "VLLM_DS4_PP_TCP_CONNECT_TIMEOUT_SECONDS", "30"
    ),
    "VLLM_DS4_PP_TCP_MIN_BYTES": _env_int("VLLM_DS4_PP_TCP_MIN_BYTES", "1"),
    "VLLM_DS4_PP_TCP_NODELAY": _env_bool("VLLM_DS4_PP_TCP_NODELAY", "1"),
    "VLLM_DS4_PP_TCP_READ_TIMEOUT_SECONDS": _env_float(
        "VLLM_DS4_PP_TCP_READ_TIMEOUT_SECONDS", "300"
    ),
    "VLLM_DS4_PP_TCP_STRIPE_MIN_BYTES": _env_int(
        "VLLM_DS4_PP_TCP_STRIPE_MIN_BYTES", "262144"
    ),
    "VLLM_DS4_PP_TCP_STRIPES": _env_int("VLLM_DS4_PP_TCP_STRIPES", "8"),
    "VLLM_DS4_PP_TCP_TENSOR_DICT": _env_bool("VLLM_DS4_PP_TCP_TENSOR_DICT"),
    "VLLM_DS4_PP_TENSOR_DICT_TP_ALL_GATHER": _env_bool(
        "VLLM_DS4_PP_TENSOR_DICT_TP_ALL_GATHER", "1"
    ),
    "VLLM_DS4_PP_TORCH_GROUP_WARMUP": _env_bool(
        "VLLM_DS4_PP_TORCH_GROUP_WARMUP", "1"
    ),
    "VLLM_DS4_PP_TORCH_PAIR_GROUPS": _env_bool("VLLM_DS4_PP_TORCH_PAIR_GROUPS"),
    "VLLM_DS4_PP_TORCH_PAIR_IFNAME_MODE": _env_str(
        "VLLM_DS4_PP_TORCH_PAIR_IFNAME_MODE", "process"
    ),
    "VLLM_DS4_PP_TORCH_PG_TENSOR_DICT": _env_bool(
        "VLLM_DS4_PP_TORCH_PG_TENSOR_DICT"
    ),
    "VLLM_DS4_PROFILE_SKIP_DUMMY_SAMPLER": _env_bool(
        "VLLM_DS4_PROFILE_SKIP_DUMMY_SAMPLER"
    ),
    "VLLM_DS4_SCHED_MAX_NEW_REQS_PER_STEP": _env_int(
        "VLLM_DS4_SCHED_MAX_NEW_REQS_PER_STEP", "0"
    ),
    "VLLM_DS4_SIMPLE_KV_READ_UNMARKED": _env_bool(
        "VLLM_DS4_SIMPLE_KV_READ_UNMARKED"
    ),
    "VLLM_DS4_SIMPLE_KV_STARTUP_RESTORE": _env_bool(
        "VLLM_DS4_SIMPLE_KV_STARTUP_RESTORE"
    ),
    "VLLM_DS4_SIMPLE_KV_STORE_UNMARKED": _env_bool(
        "VLLM_DS4_SIMPLE_KV_STORE_UNMARKED"
    ),
    "VLLM_DS4_SKIP_LOCAL_PREFIX_CACHE_READ": _env_bool(
        "VLLM_DS4_SKIP_LOCAL_PREFIX_CACHE_READ"
    ),
    "VLLM_DS4_SM12X_MQA_ROWWISE_MAX_ROWS": _env_int(
        "VLLM_DS4_SM12X_MQA_ROWWISE_MAX_ROWS", "0"
    ),
    "VLLM_DS4_SM12X_MQA_TOPK_CUDA_SELECT": _env_bool(
        "VLLM_DS4_SM12X_MQA_TOPK_CUDA_SELECT"
    ),
    "VLLM_DS4_STRICT_NATIVE_FP4": _env_bool("VLLM_DS4_STRICT_NATIVE_FP4"),
    "VLLM_DS4_TRITON_MLA_BLOCK_H": _env_int("VLLM_DS4_TRITON_MLA_BLOCK_H", "0"),
    "VLLM_DS4_TRITON_MLA_NUM_STAGES": _env_int(
        "VLLM_DS4_TRITON_MLA_NUM_STAGES", "0"
    ),
    "VLLM_DS4_VALIDATE_INPUT_IDS": _env_bool("VLLM_DS4_VALIDATE_INPUT_IDS"),
}


def register_ds4_vllm_envs() -> str:
    envs = importlib.import_module("vllm.envs")
    environment_variables = getattr(envs, "environment_variables", None)
    if not isinstance(environment_variables, dict):
        return "vllm_ds4_envs_unavailable"
    added = 0
    for name, getter in _DS4_ENV_SPECS.items():
        if name not in environment_variables:
            environment_variables[name] = getter
            added += 1
    return f"vllm_ds4_envs_registered_{added}"
