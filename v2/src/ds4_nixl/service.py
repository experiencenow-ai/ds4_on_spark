from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from typing import Any

NIXL_DEPLOYMENT_FORMAT = "ds4-nixl-deployment-v1"
NIXL_PLAN_FORMAT = "ds4-nixl-launch-plan-v1"
DEFAULT_KV_CONNECTOR = "NixlConnector"
DEFAULT_KV_LOAD_FAILURE_POLICY = "fail"


@dataclass(frozen=True)
class NixlInstance:
    instance_id: str
    role: str
    spark_node: str
    host: str
    http_port: int
    side_channel_port: int
    model_id: str
    tensor_parallel_size: int
    kv_role: str
    cuda_visible_devices: str | None
    extra_args: tuple[str, ...]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "NixlInstance":
        required = ["instance_id", "role", "spark_node", "host", "http_port", "side_channel_port", "model_id"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"NIXL instance missing fields: {missing}")
        role = str(data["role"])
        if role not in {"prefiller", "decoder"}:
            raise ValueError(f"unsupported NIXL role: {role}")
        http_port = int(data["http_port"])
        side_channel_port = int(data["side_channel_port"])
        if http_port <= 0 or side_channel_port <= 0:
            raise ValueError("NIXL ports must be positive")
        tensor_parallel_size = int(data.get("tensor_parallel_size", 1))
        if tensor_parallel_size <= 0:
            raise ValueError("tensor_parallel_size must be positive")
        default_kv_role = "kv_producer" if role == "prefiller" else "kv_consumer"
        kv_role = str(data.get("kv_role", default_kv_role))
        if kv_role not in {"kv_producer", "kv_consumer", "kv_both"}:
            raise ValueError(f"unsupported kv_role: {kv_role}")
        extra_args = tuple(str(item) for item in data.get("extra_args", []))
        return NixlInstance(
            instance_id=str(data["instance_id"]),
            role=role,
            spark_node=str(data["spark_node"]),
            host=str(data["host"]),
            http_port=http_port,
            side_channel_port=side_channel_port,
            model_id=str(data["model_id"]),
            tensor_parallel_size=tensor_parallel_size,
            kv_role=kv_role,
            cuda_visible_devices=str(data["cuda_visible_devices"]) if data.get("cuda_visible_devices") is not None else None,
            extra_args=extra_args,
        )


@dataclass(frozen=True)
class NixlDeployment:
    deployment_id: str
    profile_id: str
    connector_backends: tuple[str, ...]
    ucx_tls: str
    ucx_net_devices: str
    kv_load_failure_policy: str
    kv_buffer_device: str
    prefiller: NixlInstance
    decoder: NixlInstance
    proxy_host: str
    proxy_port: int
    proxy_module: str
    vllm_bin: str
    python_bin: str
    pythonpath: str | None
    working_directory: str | None
    extra_env: dict[str, str]
    use_enforce_eager: bool
    enable_cross_layers_blocks: bool

    @staticmethod
    def from_json(data: dict[str, Any]) -> "NixlDeployment":
        if data.get("format") != NIXL_DEPLOYMENT_FORMAT:
            raise ValueError(f"unsupported NIXL deployment format: {data.get('format')!r}")
        required = ["deployment_id", "profile_id", "prefiller", "decoder", "proxy"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"NIXL deployment missing fields: {missing}")
        proxy = dict(data["proxy"])
        extra_env = {str(key): str(value) for key, value in dict(data.get("extra_env", {})).items()}
        return NixlDeployment(
            deployment_id=str(data["deployment_id"]),
            profile_id=str(data["profile_id"]),
            connector_backends=tuple(str(item) for item in data.get("connector_backends", ["UCX"])),
            ucx_tls=str(data.get("ucx_tls", "all")),
            ucx_net_devices=str(data.get("ucx_net_devices", "all")),
            kv_load_failure_policy=str(data.get("kv_load_failure_policy", DEFAULT_KV_LOAD_FAILURE_POLICY)),
            kv_buffer_device=str(data.get("kv_buffer_device", "cuda")),
            prefiller=NixlInstance.from_json(dict(data["prefiller"])),
            decoder=NixlInstance.from_json(dict(data["decoder"])),
            proxy_host=str(proxy.get("host", "127.0.0.1")),
            proxy_port=int(proxy.get("port", 8192)),
            proxy_module=str(proxy.get("module", "ds4_nixl.proxy")),
            vllm_bin=str(data.get("vllm_bin", "vllm")),
            python_bin=str(data.get("python_bin", "python3")),
            pythonpath=str(data["pythonpath"]) if data.get("pythonpath") is not None else None,
            working_directory=str(data["working_directory"]) if data.get("working_directory") is not None else None,
            extra_env=extra_env,
            use_enforce_eager=bool(data.get("use_enforce_eager", True)),
            enable_cross_layers_blocks=bool(data.get("enable_cross_layers_blocks", False)),
        )

    @staticmethod
    def load(path: str | Path) -> "NixlDeployment":
        with Path(path).open("r", encoding="utf-8") as handle:
            return NixlDeployment.from_json(json.load(handle))


def nixl_kv_transfer_config(*, role: str, deployment: NixlDeployment, instance: NixlInstance | None = None) -> dict[str, Any]:
    if role not in {"kv_producer", "kv_consumer", "kv_both"}:
        raise ValueError(f"unsupported kv_role: {role}")
    extra_config: dict[str, Any] = {"backends": list(deployment.connector_backends)}
    if deployment.enable_cross_layers_blocks:
        extra_config["enable_cross_layers_blocks"] = "True"
    config: dict[str, Any] = {
        "kv_connector": DEFAULT_KV_CONNECTOR,
        "kv_role": role,
        "kv_load_failure_policy": deployment.kv_load_failure_policy,
        "kv_buffer_device": deployment.kv_buffer_device,
        "kv_connector_extra_config": extra_config,
    }
    if instance is not None:
        config.update({"kv_ip": instance.host, "kv_port": instance.side_channel_port})
    return config


def plan_deployment(deployment: NixlDeployment) -> dict[str, Any]:
    prefiller = _instance_plan(deployment.prefiller, deployment)
    decoder = _instance_plan(deployment.decoder, deployment)
    proxy = _proxy_plan(deployment)
    return {
        "format": NIXL_PLAN_FORMAT,
        "deployment_id": deployment.deployment_id,
        "profile_id": deployment.profile_id,
        "state": "planned",
        "notes": [
            "NIXL deployment is Spark-side and must be live-tested on matching vLLM/NIXL builds.",
            "Requests should go to the proxy endpoint, not directly to prefiller or decoder.",
            "Use kv_load_failure_policy=fail to avoid hidden decode-side recompute jitter.",
        ],
        "prefiller": prefiller,
        "decoder": decoder,
        "proxy": proxy,
    }


def write_launch_scripts(deployment: NixlDeployment, output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    plan = plan_deployment(deployment)
    script_paths: dict[str, str] = {}
    for key in ("prefiller", "decoder", "proxy"):
        path = root / f"start_{key}.sh"
        path.write_text(_script_text(plan[key], deployment), encoding="utf-8")
        path.chmod(0o755)
        script_paths[key] = str(path)
    manifest = {
        "format": "ds4-nixl-launch-scripts-v1",
        "deployment_id": deployment.deployment_id,
        "scripts": script_paths,
        "plan": plan,
    }
    (root / "nixl_launch_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _base_env(deployment: NixlDeployment) -> dict[str, str]:
    env = dict(deployment.extra_env)
    if deployment.pythonpath:
        env["PYTHONPATH"] = deployment.pythonpath
    return env


def _instance_plan(instance: NixlInstance, deployment: NixlDeployment) -> dict[str, Any]:
    kv_config = nixl_kv_transfer_config(role=instance.kv_role, deployment=deployment, instance=instance)
    env = _base_env(deployment)
    env.update(
        {
            "UCX_TLS": deployment.ucx_tls,
            "UCX_NET_DEVICES": deployment.ucx_net_devices,
            "VLLM_NIXL_SIDE_CHANNEL_HOST": instance.host,
            "VLLM_NIXL_SIDE_CHANNEL_PORT": str(instance.side_channel_port),
        }
    )
    if instance.cuda_visible_devices is not None:
        env["CUDA_VISIBLE_DEVICES"] = instance.cuda_visible_devices
    argv = [
        deployment.vllm_bin,
        "serve",
        instance.model_id,
        "--host",
        "0.0.0.0",
        "--port",
        str(instance.http_port),
        "--tensor-parallel-size",
        str(instance.tensor_parallel_size),
        "--kv-transfer-config",
        json.dumps(kv_config, sort_keys=True),
    ]
    if deployment.use_enforce_eager:
        argv.append("--enforce-eager")
    argv.extend(instance.extra_args)
    return {
        "instance_id": instance.instance_id,
        "role": instance.role,
        "spark_node": instance.spark_node,
        "host": instance.host,
        "http_port": instance.http_port,
        "side_channel_port": instance.side_channel_port,
        "env": env,
        "argv": argv,
        "command": _format_env_command(env, argv),
        "kv_transfer_config": kv_config,
    }


def _proxy_plan(deployment: NixlDeployment) -> dict[str, Any]:
    env = _base_env(deployment)
    argv = [
        deployment.python_bin,
        "-m",
        deployment.proxy_module,
        "--host",
        deployment.proxy_host,
        "--port",
        str(deployment.proxy_port),
        "--prefiller-hosts",
        deployment.prefiller.host,
        "--prefiller-ports",
        str(deployment.prefiller.http_port),
        "--decoder-hosts",
        deployment.decoder.host,
        "--decoder-ports",
        str(deployment.decoder.http_port),
    ]
    return {
        "host": deployment.proxy_host,
        "port": deployment.proxy_port,
        "env": env,
        "argv": argv,
        "command": _format_env_command(env, argv),
        "openai_base_url": f"http://{deployment.proxy_host}:{deployment.proxy_port}",
    }


def _format_env_command(env: dict[str, str], argv: list[str]) -> str:
    parts = [f"{key}={shlex.quote(value)}" for key, value in sorted(env.items())]
    parts.extend(shlex.quote(part) for part in argv)
    return " ".join(parts)


def _script_text(section: dict[str, Any], deployment: NixlDeployment) -> str:
    lines = ["#!/usr/bin/env bash", "set -euo pipefail"]
    if deployment.working_directory:
        lines.append(f"cd {shlex.quote(deployment.working_directory)}")
    lines.extend([section["command"], ""])
    return "\n".join(lines)
