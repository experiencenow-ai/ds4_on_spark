from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from typing import Any

KV_CACHE_DEPLOYMENT_FORMAT = "ds4-vllm-kv-cache-deployment-v1"
KV_CACHE_PLAN_FORMAT = "ds4-vllm-kv-cache-launch-plan-v1"


@dataclass(frozen=True)
class KvCacheConnector:
    connector_id: str
    kv_connector: str
    kv_role: str
    kv_connector_module_path: str | None
    kv_connector_extra_config: dict[str, Any]
    install_packages: tuple[str, ...]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "KvCacheConnector":
        connector_id = str(data.get("connector_id", data.get("kind", "lmcache_dynamic")))
        kv_connector = str(data.get("kv_connector", _default_connector_name(connector_id)))
        kv_role = str(data.get("kv_role", "kv_both"))
        if kv_role not in {"kv_both", "kv_producer", "kv_consumer"}:
            raise ValueError(f"unsupported kv_role: {kv_role}")
        module_path = data.get("kv_connector_module_path", _default_connector_module(connector_id))
        return KvCacheConnector(
            connector_id=connector_id,
            kv_connector=kv_connector,
            kv_role=kv_role,
            kv_connector_module_path=str(module_path) if module_path else None,
            kv_connector_extra_config=dict(data.get("kv_connector_extra_config", {})),
            install_packages=tuple(str(item) for item in data.get("install_packages", _default_packages(connector_id))),
        )


@dataclass(frozen=True)
class KvCacheDeployment:
    deployment_id: str
    profile_id: str
    spark_node: str
    worker_nodes: tuple[str, ...]
    model_id: str
    served_model_name: str | None
    host: str
    http_port: int
    tensor_parallel_size: int
    vllm_bin: str
    python_bin: str
    working_directory: str | None
    pythonpath: str | None
    extra_env: dict[str, str]
    cache_directories: tuple[str, ...]
    connector: KvCacheConnector
    extra_args: tuple[str, ...]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "KvCacheDeployment":
        if data.get("format") != KV_CACHE_DEPLOYMENT_FORMAT:
            raise ValueError(f"unsupported KV cache deployment format: {data.get('format')!r}")
        required = ["deployment_id", "profile_id", "spark_node", "model_id", "connector"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"KV cache deployment missing fields: {missing}")
        http_port = int(data.get("http_port", 8000))
        tensor_parallel_size = int(data.get("tensor_parallel_size", 1))
        if http_port <= 0 or tensor_parallel_size <= 0:
            raise ValueError("http_port and tensor_parallel_size must be positive")
        return KvCacheDeployment(
            deployment_id=str(data["deployment_id"]),
            profile_id=str(data["profile_id"]),
            spark_node=str(data["spark_node"]),
            worker_nodes=tuple(str(item) for item in data.get("worker_nodes", [data["spark_node"]])),
            model_id=str(data["model_id"]),
            served_model_name=str(data["served_model_name"]) if data.get("served_model_name") else None,
            host=str(data.get("host", "0.0.0.0")),
            http_port=http_port,
            tensor_parallel_size=tensor_parallel_size,
            vllm_bin=str(data.get("vllm_bin", "vllm")),
            python_bin=str(data.get("python_bin", _default_python_bin(str(data.get("vllm_bin", "vllm"))))),
            working_directory=str(data["working_directory"]) if data.get("working_directory") else None,
            pythonpath=str(data["pythonpath"]) if data.get("pythonpath") else None,
            extra_env={str(key): str(value) for key, value in dict(data.get("extra_env", {})).items()},
            cache_directories=tuple(str(item) for item in data.get("cache_directories", [])),
            connector=KvCacheConnector.from_json(dict(data["connector"])),
            extra_args=tuple(str(item) for item in data.get("extra_args", [])),
        )

    @staticmethod
    def load(path: str | Path) -> "KvCacheDeployment":
        with Path(path).open("r", encoding="utf-8") as handle:
            return KvCacheDeployment.from_json(json.load(handle))


def kv_transfer_config(connector: KvCacheConnector) -> dict[str, Any]:
    config: dict[str, Any] = {
        "kv_connector": connector.kv_connector,
        "kv_role": connector.kv_role,
    }
    if connector.kv_connector_module_path:
        config["kv_connector_module_path"] = connector.kv_connector_module_path
    if connector.kv_connector_extra_config:
        config["kv_connector_extra_config"] = connector.kv_connector_extra_config
    return config


def plan_deployment(deployment: KvCacheDeployment) -> dict[str, Any]:
    env = dict(deployment.extra_env)
    if deployment.pythonpath:
        env["PYTHONPATH"] = deployment.pythonpath
    client_host = deployment.spark_node if deployment.host in {"0.0.0.0", "::"} else deployment.host
    argv = _vllm_argv(deployment)
    return_plan = {
        "format": KV_CACHE_PLAN_FORMAT,
        "deployment_id": deployment.deployment_id,
        "profile_id": deployment.profile_id,
        "state": "planned",
        "spark_node": deployment.spark_node,
        "worker_nodes": list(deployment.worker_nodes),
        "logical_service_count": 1,
        "model_instance_count": 1,
        "listen_base_url": f"http://{deployment.host}:{deployment.http_port}",
        "openai_base_url": f"http://{client_host}:{deployment.http_port}",
        "connector": {
            "connector_id": deployment.connector.connector_id,
            "install_packages": list(deployment.connector.install_packages),
            "kv_transfer_config": kv_transfer_config(deployment.connector),
        },
        "notes": _plan_notes(),
        "vllm": {
            "spark_node": deployment.spark_node,
            "worker_nodes": list(deployment.worker_nodes),
            "working_directory": deployment.working_directory,
            "env": env,
            "argv": argv,
            "command": _format_env_command(env, argv),
        },
    }
    return return_plan


def _vllm_argv(deployment: KvCacheDeployment) -> list[str]:
    argv = [
        deployment.vllm_bin,
        "serve",
        deployment.model_id,
        "--host",
        deployment.host,
        "--port",
        str(deployment.http_port),
        "--tensor-parallel-size",
        str(deployment.tensor_parallel_size),
        "--kv-transfer-config",
        json.dumps(kv_transfer_config(deployment.connector), sort_keys=True),
    ]
    if deployment.served_model_name:
        argv.extend(["--served-model-name", deployment.served_model_name])
    argv.extend(_dedupe_args(deployment.extra_args, present=set(argv)))
    return argv


def _plan_notes() -> list[str]:
    return [
        "Single-service KV cache: one vLLM serving lane owns model execution, batching, and external KV load/store.",
        "Tensor parallel workers may span multiple Sparks, but this is not a prefiller/decoder split.",
        "Use queue-warm-prefixes or normal repeated shared_prefix requests to seed reusable prompt skeletons.",
        "No second model-serving instance is required for this path.",
    ]


def write_launch_scripts(deployment: KvCacheDeployment, output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    plan = plan_deployment(deployment)
    scripts = {
        "install": root / "00_install_kv_cache_deps.sh",
        "start_vllm": root / "start_vllm_cache.sh",
    }
    scripts["install"].write_text(_install_script(deployment), encoding="utf-8")
    scripts["start_vllm"].write_text(_start_script(plan["vllm"], deployment), encoding="utf-8")
    for path in scripts.values():
        path.chmod(0o755)
    manifest = {
        "format": "ds4-vllm-kv-cache-launch-scripts-v1",
        "deployment_id": deployment.deployment_id,
        "scripts": {key: str(path) for key, path in scripts.items()},
        "plan": plan,
    }
    (root / "kv_cache_launch_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _default_connector_name(connector_id: str) -> str:
    if connector_id == "lmcache_dynamic":
        return "LMCacheConnectorV1Dynamic"
    if connector_id == "lmcache":
        return "LMCacheConnectorV1"
    if connector_id == "offloading":
        return "OffloadingConnector"
    return connector_id


def _default_connector_module(connector_id: str) -> str | None:
    if connector_id == "lmcache_dynamic":
        return "lmcache.integration.vllm.lmcache_connector_v1"
    return None


def _default_packages(connector_id: str) -> list[str]:
    if connector_id.startswith("lmcache"):
        return ["lmcache"]
    return []


def _dedupe_args(extra_args: tuple[str, ...], *, present: set[str]) -> list[str]:
    out: list[str] = []
    skip_next = False
    for index, item in enumerate(extra_args):
        if skip_next:
            skip_next = False
            continue
        if item in present:
            skip_next = index + 1 < len(extra_args) and not extra_args[index + 1].startswith("--")
            continue
        out.append(item)
    return out


def _format_env_command(env: dict[str, str], argv: list[str]) -> str:
    pieces = [f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())]
    pieces.extend(shlex.quote(item) for item in argv)
    return " ".join(pieces)


def _install_script(deployment: KvCacheDeployment) -> str:
    packages = " ".join(shlex.quote(item) for item in deployment.connector.install_packages)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "cd " + shlex.quote(deployment.working_directory or "."),
    ]
    if packages:
        lines.append(shlex.quote(deployment.python_bin) + " -m pip install --upgrade " + packages)
    else:
        lines.append("echo '[ds4-kvcache] no connector packages requested'")
    for path in deployment.cache_directories:
        lines.append("mkdir -p " + shlex.quote(path))
    return "\n".join(lines) + "\n"


def _default_python_bin(vllm_bin: str) -> str:
    if "/" not in vllm_bin:
        return "python3"
    return vllm_bin.rsplit("/", 1)[0] + "/python"


def _start_script(vllm_plan: dict[str, Any], deployment: KvCacheDeployment) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
    ]
    if deployment.working_directory:
        lines.append("cd " + shlex.quote(deployment.working_directory))
    lines.append("exec " + vllm_plan["command"])
    return "\n".join(lines) + "\n"
