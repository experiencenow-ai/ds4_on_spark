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
    install_args: tuple[str, ...]
    wheel_dir: str | None

    @staticmethod
    def from_json(data: dict[str, Any]) -> "KvCacheConnector":
        connector_id = str(data.get("connector_id", data.get("kind", "offloading")))
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
            install_args=tuple(str(item) for item in data.get("install_args", [])),
            wheel_dir=str(data["wheel_dir"]) if data.get("wheel_dir") else None,
        )


@dataclass(frozen=True)
class LmcacheServer:
    server_id: str
    bin: str
    host: str
    port: int
    http_port: int
    l1_size_gb: int
    eviction_policy: str
    chunk_size: int
    l1_use_lazy: bool
    l1_init_size_gb: int | None
    max_workers: int | None
    hash_algorithm: str | None
    l2_adapter: dict[str, Any] | None
    extra_args: tuple[str, ...]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "LmcacheServer":
        if data.get("kind", "lmcache_mp") != "lmcache_mp":
            raise ValueError(f"unsupported cache_server kind: {data.get('kind')!r}")
        server = LmcacheServer(
            server_id=str(data.get("server_id", "lmcache_mp")),
            bin=str(data.get("bin", "lmcache")),
            host=str(data.get("host", "127.0.0.1")),
            port=int(data.get("port", 5555)),
            http_port=int(data.get("http_port", 8080)),
            l1_size_gb=int(data["l1_size_gb"]),
            eviction_policy=str(data.get("eviction_policy", "LRU")),
            chunk_size=int(data.get("chunk_size", 256)),
            l1_use_lazy=bool(data.get("l1_use_lazy", True)),
            l1_init_size_gb=int(data["l1_init_size_gb"]) if data.get("l1_init_size_gb") is not None else None,
            max_workers=int(data["max_workers"]) if data.get("max_workers") is not None else None,
            hash_algorithm=str(data["hash_algorithm"]) if data.get("hash_algorithm") else None,
            l2_adapter=dict(data["l2_adapter"]) if data.get("l2_adapter") else None,
            extra_args=tuple(str(item) for item in data.get("extra_args", [])),
        )
        _validate_lmcache_server(server)
        return server


@dataclass(frozen=True)
class KvCacheDeployment:
    deployment_id: str
    runtime_contract_id: str | None
    vllm_fork: str | None
    vllm_source_commit: str | None
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
    cache_server: LmcacheServer | None
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
        deployment = KvCacheDeployment(
            deployment_id=str(data["deployment_id"]),
            runtime_contract_id=str(data["runtime_contract_id"]) if data.get("runtime_contract_id") else None,
            vllm_fork=str(data["vllm_fork"]) if data.get("vllm_fork") else None,
            vllm_source_commit=str(data["vllm_source_commit"]) if data.get("vllm_source_commit") else None,
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
            cache_server=LmcacheServer.from_json(dict(data["cache_server"])) if data.get("cache_server") else None,
            extra_args=tuple(str(item) for item in data.get("extra_args", [])),
        )
        _validate_deployment(deployment)
        return deployment

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


def _validate_lmcache_server(server: LmcacheServer) -> None:
    if server.port <= 0 or server.http_port <= 0:
        raise ValueError("LMCache server ports must be positive")
    if server.l1_size_gb <= 0:
        raise ValueError("LMCache l1_size_gb must be positive")
    if server.chunk_size <= 0:
        raise ValueError("LMCache chunk_size must be positive")


def _validate_deployment(deployment: KvCacheDeployment) -> None:
    if deployment.model_id == "deepseek-ai/DeepSeek-V4-Flash" and deployment.connector.kv_connector.startswith("LMCache"):
        raise ValueError(
            "LMCache connectors are not a valid DSV4 long-context deployment "
            "until they implement vLLM SupportsHMA; use HMA-compatible CPU KV "
            "offload or a proven HMA connector"
        )
    if deployment.model_id == "deepseek-ai/DeepSeek-V4-Flash" and deployment.connector.kv_connector == "OffloadingConnector":
        raise ValueError(
            "DSV4 long-context KV offload must use SimpleCPUOffloadConnector; "
            "plain OffloadingConnector does not prove the HMA-aware persistent "
            "SimpleCPUOffload path"
        )
    if deployment.connector.connector_id == "lmcache_mp" and deployment.cache_server is None:
        raise ValueError("LMCacheMPConnector deployments must define cache_server")
    if deployment.cache_server is not None and deployment.connector.connector_id != "lmcache_mp":
        raise ValueError("cache_server is only supported with connector_id=lmcache_mp")


def plan_deployment(deployment: KvCacheDeployment) -> dict[str, Any]:
    env = dict(deployment.extra_env)
    if deployment.pythonpath:
        env["PYTHONPATH"] = deployment.pythonpath
    connector = _connector_with_server(deployment.connector, deployment.cache_server)
    client_host = deployment.spark_node if deployment.host in {"0.0.0.0", "::"} else deployment.host
    argv = _vllm_argv(deployment, connector)
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
            "connector_id": connector.connector_id,
            "install_packages": list(connector.install_packages),
            "install_args": list(connector.install_args),
            "wheel_dir": connector.wheel_dir,
            "kv_transfer_config": kv_transfer_config(connector),
        },
        "runtime": _runtime_plan(deployment),
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
    if deployment.cache_server is not None:
        return_plan["cache_server"] = _lmcache_server_plan(deployment.cache_server, deployment)
    return return_plan


def _connector_with_server(connector: KvCacheConnector, server: LmcacheServer | None) -> KvCacheConnector:
    if server is None:
        return connector
    extra = dict(connector.kv_connector_extra_config)
    extra["lmcache.mp.host"] = server.host
    extra["lmcache.mp.port"] = server.port
    return KvCacheConnector(
        connector_id=connector.connector_id,
        kv_connector=connector.kv_connector,
        kv_role=connector.kv_role,
        kv_connector_module_path=connector.kv_connector_module_path,
        kv_connector_extra_config=extra,
        install_packages=connector.install_packages,
        install_args=connector.install_args,
        wheel_dir=connector.wheel_dir,
    )


def _runtime_plan(deployment: KvCacheDeployment) -> dict[str, Any]:
    return {
        "runtime_contract_id": deployment.runtime_contract_id,
        "vllm_fork": deployment.vllm_fork,
        "vllm_source_commit": deployment.vllm_source_commit,
    }


def _vllm_argv(deployment: KvCacheDeployment, connector: KvCacheConnector) -> list[str]:
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
        json.dumps(kv_transfer_config(connector), sort_keys=True),
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


def _lmcache_server_plan(server: LmcacheServer, deployment: KvCacheDeployment) -> dict[str, Any]:
    client_host = deployment.spark_node if server.host in {"0.0.0.0", "::"} else server.host
    argv = _lmcache_argv(server)
    return {
        "kind": "lmcache_mp",
        "server_id": server.server_id,
        "spark_node": deployment.spark_node,
        "listen_url": f"tcp://{server.host}:{server.port}",
        "management_url": f"http://{client_host}:{server.http_port}",
        "argv": argv,
        "command": _format_env_command(deployment.extra_env, argv),
    }


def _lmcache_argv(server: LmcacheServer) -> list[str]:
    argv = [
        server.bin,
        "server",
        "--host",
        server.host,
        "--port",
        str(server.port),
        "--http-port",
        str(server.http_port),
        "--l1-size-gb",
        str(server.l1_size_gb),
        "--eviction-policy",
        server.eviction_policy,
        "--chunk-size",
        str(server.chunk_size),
    ]
    if server.l1_use_lazy:
        argv.append("--l1-use-lazy")
    if server.l1_init_size_gb is not None:
        argv.extend(["--l1-init-size-gb", str(server.l1_init_size_gb)])
    if server.max_workers is not None:
        argv.extend(["--max-workers", str(server.max_workers)])
    if server.hash_algorithm is not None:
        argv.extend(["--hash-algorithm", server.hash_algorithm])
    if server.l2_adapter is not None:
        argv.extend(["--l2-adapter", json.dumps(server.l2_adapter, sort_keys=True)])
    argv.extend(server.extra_args)
    return argv


def write_launch_scripts(deployment: KvCacheDeployment, output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    plan = plan_deployment(deployment)
    scripts = {
        "install": root / "00_install_kv_cache_deps.sh",
        "start_vllm": root / "start_vllm_cache.sh",
    }
    if deployment.cache_server is not None:
        scripts["start_cache_server"] = root / "start_lmcache_server.sh"
    scripts["install"].write_text(_install_script(deployment), encoding="utf-8")
    scripts["start_vllm"].write_text(_start_script(plan["vllm"], deployment), encoding="utf-8")
    if deployment.cache_server is not None:
        scripts["start_cache_server"].write_text(_start_script(plan["cache_server"], deployment), encoding="utf-8")
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
    if connector_id == "lmcache_mp":
        return "LMCacheMPConnector"
    if connector_id == "lmcache_dynamic":
        return "LMCacheConnectorV1Dynamic"
    if connector_id == "lmcache":
        return "LMCacheConnectorV1"
    if connector_id == "simple_cpu_offload":
        return "SimpleCPUOffloadConnector"
    if connector_id == "offloading":
        return "OffloadingConnector"
    return connector_id


def _default_connector_module(connector_id: str) -> str | None:
    if connector_id == "lmcache_dynamic":
        return "lmcache.integration.vllm.lmcache_connector_v1"
    return None


def _default_packages(connector_id: str) -> list[str]:
    if connector_id.startswith("lmcache"):
        return ["lmcache==0.4.5"]
    return []


def _dedupe_args(extra_args: tuple[str, ...], *, present: set[str]) -> list[str]:
    out: list[str] = []
    skip_next = False
    for index, item in enumerate(extra_args):
        if skip_next:
            skip_next = False
            continue
        if item.startswith("--") and item in present:
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
    if deployment.connector.connector_id == "lmcache_mp" and packages:
        wheel_dir = deployment.connector.wheel_dir or "/tmp/ds4_lmcache_wheels"
        wheel_glob = _lmcache_wheel_glob(deployment.connector.install_packages)
        wheel_argv = [deployment.python_bin, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", wheel_dir]
        wheel_argv.extend(deployment.connector.install_packages)
        lines.append("mkdir -p " + shlex.quote(wheel_dir))
        lines.append(_format_env_command(deployment.extra_env, wheel_argv))
        lines.append("wheel=$(find " + shlex.quote(wheel_dir) + " -maxdepth 1 -name " + shlex.quote(wheel_glob) + " -print -quit)")
        lines.append('if [ -z "${wheel}" ]; then echo "[ds4-kvcache] LMCache wheel not found" >&2; exit 2; fi')
        install_argv = [deployment.python_bin, "-m", "pip", "install", "--no-deps"]
        lines.append(_format_env_command(deployment.extra_env, install_argv) + ' "${wheel}"')
    elif packages:
        argv = [deployment.python_bin, "-m", "pip", "install", "--upgrade"]
        argv.extend(deployment.connector.install_args)
        argv.extend(deployment.connector.install_packages)
        lines.append(_format_env_command(deployment.extra_env, argv))
    else:
        lines.append("echo '[ds4-kvcache] no connector packages requested'")
    for path in deployment.cache_directories:
        lines.append("mkdir -p " + shlex.quote(path))
    return "\n".join(lines) + "\n"


def _lmcache_wheel_glob(packages: tuple[str, ...]) -> str:
    for package in packages:
        if package.startswith("lmcache=="):
            return "lmcache-" + package.split("==", 1)[1] + "-*.whl"
    return "lmcache-*.whl"


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
