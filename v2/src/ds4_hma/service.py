from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from typing import Any

HMA_DEPLOYMENT_FORMAT = "ds4-dsv4-hma-persistent-deployment-v1"
HMA_PLAN_FORMAT = "ds4-dsv4-hma-persistent-plan-v1"
DEFAULT_CONNECTOR = "DS4HmaPersistentConnector"
DEFAULT_CONNECTOR_MODULE = "ds4_hma.vllm_connector"
DEFAULT_KV_LOAD_FAILURE_POLICY = "fail"


@dataclass(frozen=True)
class Dsv4HmaDeployment:
    deployment_id: str
    profile_id: str
    model_id: str
    spark_node: str
    host: str
    port: int
    tensor_parallel_size: int
    cuda_visible_devices: str | None
    store_root: str
    tokenizer_hash: str
    hma_layout: str
    kv_load_failure_policy: str
    kv_buffer_device: str
    connector_module_path: str
    connector_class: str
    extra_args: tuple[str, ...]
    env: dict[str, str]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Dsv4HmaDeployment":
        if data.get("format") != HMA_DEPLOYMENT_FORMAT:
            raise ValueError(f"unsupported HMA deployment format: {data.get('format')!r}")
        required = ["deployment_id", "profile_id", "model_id", "spark_node", "host", "port", "store_root"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"HMA deployment missing fields: {missing}")
        tensor_parallel_size = int(data.get("tensor_parallel_size", 1))
        if tensor_parallel_size <= 0:
            raise ValueError("tensor_parallel_size must be positive")
        port = int(data["port"])
        if port <= 0:
            raise ValueError("port must be positive")
        return Dsv4HmaDeployment(
            deployment_id=str(data["deployment_id"]),
            profile_id=str(data["profile_id"]),
            model_id=str(data["model_id"]),
            spark_node=str(data["spark_node"]),
            host=str(data["host"]),
            port=port,
            tensor_parallel_size=tensor_parallel_size,
            cuda_visible_devices=str(data["cuda_visible_devices"]) if data.get("cuda_visible_devices") is not None else None,
            store_root=str(data["store_root"]),
            tokenizer_hash=str(data.get("tokenizer_hash", "unknown-tokenizer")),
            hma_layout=str(data.get("hma_layout", "dsv4_hma_mla_sliding_indexer_compressor_v1")),
            kv_load_failure_policy=str(data.get("kv_load_failure_policy", DEFAULT_KV_LOAD_FAILURE_POLICY)),
            kv_buffer_device=str(data.get("kv_buffer_device", "cuda")),
            connector_module_path=str(data.get("connector_module_path", DEFAULT_CONNECTOR_MODULE)),
            connector_class=str(data.get("connector_class", DEFAULT_CONNECTOR)),
            extra_args=tuple(str(item) for item in data.get("extra_args", [])),
            env={str(key): str(value) for key, value in dict(data.get("env", {})).items()},
        )

    @staticmethod
    def load(path: str | Path) -> "Dsv4HmaDeployment":
        with Path(path).open("r", encoding="utf-8") as handle:
            return Dsv4HmaDeployment.from_json(json.load(handle))


def hma_kv_transfer_config(deployment: Dsv4HmaDeployment) -> dict[str, Any]:
    return {
        "kv_connector": deployment.connector_class,
        "kv_connector_module_path": deployment.connector_module_path,
        "kv_role": "kv_both",
        "kv_load_failure_policy": deployment.kv_load_failure_policy,
        "kv_buffer_device": deployment.kv_buffer_device,
        "kv_connector_extra_config": {
            "ds4_hma_store_root": deployment.store_root,
            "ds4_hma_store_format": "ds4-dsv4-hma-state-package-v1",
            "ds4_hma_tokenizer_hash": deployment.tokenizer_hash,
            "ds4_hma_layout": deployment.hma_layout,
            "ds4_hma_hard_fail": "True",
            "ds4_hma_required_parts": [
                "mla_or_latent_kv",
                "sliding_window_state",
                "indexer_state",
                "compressor_state",
                "hma_group_blocks",
            ],
        },
    }


def plan_deployment(deployment: Dsv4HmaDeployment) -> dict[str, Any]:
    kv_config = hma_kv_transfer_config(deployment)
    env = {
        "DS4_HMA_STORE_ROOT": deployment.store_root,
        "DS4_HMA_TOKENIZER_HASH": deployment.tokenizer_hash,
    }
    env.update(deployment.env)
    if deployment.cuda_visible_devices is not None:
        env["CUDA_VISIBLE_DEVICES"] = deployment.cuda_visible_devices
    argv = [
        "vllm",
        "serve",
        deployment.model_id,
        "--host",
        "0.0.0.0",
        "--port",
        str(deployment.port),
        "--tensor-parallel-size",
        str(deployment.tensor_parallel_size),
        "--kv-transfer-config",
        json.dumps(kv_config, sort_keys=True),
    ]
    argv.extend(deployment.extra_args)
    return {
        "format": HMA_PLAN_FORMAT,
        "deployment_id": deployment.deployment_id,
        "profile_id": deployment.profile_id,
        "state": "experimental_fail_closed",
        "spark_node": deployment.spark_node,
        "openai_base_url": f"http://{deployment.host}:{deployment.port}",
        "env": env,
        "argv": argv,
        "command": _format_env_command(env, argv),
        "kv_transfer_config": kv_config,
        "connector_contract": {
            "dynamic_module": deployment.connector_module_path,
            "connector_class": deployment.connector_class,
            "supports_hma": True,
            "persistent_store_root": deployment.store_root,
            "hard_gate": "Do not mark production_eligible until live DSV4 HMA state save, process restart, and reload pass.",
        },
        "notes": [
            "This is not generic LMCache. It uses a DSV4/HMA-specific state package contract.",
            "The connector must persist compressed/sliding/indexer/compressor state, not only standard KV tensors.",
            "It is pinned-only until live vLLM HMA extractor hooks are verified.",
        ],
    }


def write_launch_scripts(deployment: Dsv4HmaDeployment, output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    plan = plan_deployment(deployment)
    start_path = root / "start_dsv4_hma_persistent.sh"
    start_path.write_text(_script_text(plan["command"]), encoding="utf-8")
    start_path.chmod(0o755)
    manifest = {
        "format": "ds4-dsv4-hma-launch-scripts-v1",
        "deployment_id": deployment.deployment_id,
        "scripts": {"server": str(start_path)},
        "plan": plan,
    }
    (root / "hma_launch_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _format_env_command(env: dict[str, str], argv: list[str]) -> str:
    parts = [f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())]
    parts.extend(shlex.quote(part) for part in argv)
    return " ".join(parts)


def _script_text(command: str) -> str:
    return "\n".join(["#!/usr/bin/env bash", "set -euo pipefail", command, ""])
