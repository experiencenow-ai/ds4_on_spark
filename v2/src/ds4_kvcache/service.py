from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
from typing import Any

from ds4_infer.pipelines import even_layer_partition
from ds4_transfer.service import TransferNode, TransferTopology

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
    pipeline_parallel_size: int
    master_addr: str | None
    master_port: int | None
    layer_partition: tuple[int, ...]
    total_layers: int | None
    node_rank: int | None
    vllm_bin: str
    python_bin: str
    working_directory: str | None
    pythonpath: str | None
    fabric_topology: str | None
    extra_env: dict[str, str]
    cache_directories: tuple[str, ...]
    connector: KvCacheConnector
    cache_server: LmcacheServer | None
    lmcache_config: dict[str, Any]
    extra_args: tuple[str, ...]
    cache_sharding: str
    text_only: bool

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
        pipeline_parallel_size = int(data.get("pipeline_parallel_size", 1))
        worker_nodes = tuple(str(item) for item in data.get("pipeline_nodes", data.get("worker_nodes", [data["spark_node"]])))
        total_layers = int(data["total_layers"]) if data.get("total_layers") is not None else None
        layer_partition = _deployment_layer_partition(data, worker_nodes=worker_nodes, stage_count=pipeline_parallel_size, total_layers=total_layers)
        if http_port <= 0 or tensor_parallel_size <= 0 or pipeline_parallel_size <= 0:
            raise ValueError("http_port, tensor_parallel_size, and pipeline_parallel_size must be positive")
        deployment = KvCacheDeployment(
            deployment_id=str(data["deployment_id"]),
            runtime_contract_id=str(data["runtime_contract_id"]) if data.get("runtime_contract_id") else None,
            vllm_fork=str(data["vllm_fork"]) if data.get("vllm_fork") else None,
            vllm_source_commit=str(data["vllm_source_commit"]) if data.get("vllm_source_commit") else None,
            profile_id=str(data["profile_id"]),
            spark_node=str(data["spark_node"]),
            worker_nodes=worker_nodes,
            model_id=str(data["model_id"]),
            served_model_name=str(data["served_model_name"]) if data.get("served_model_name") else None,
            host=str(data.get("host", "0.0.0.0")),
            http_port=http_port,
            tensor_parallel_size=tensor_parallel_size,
            pipeline_parallel_size=pipeline_parallel_size,
            master_addr=str(data["master_addr"]) if data.get("master_addr") else str(data["spark_node"]),
            master_port=int(data["master_port"]) if data.get("master_port") is not None else None,
            layer_partition=layer_partition,
            total_layers=total_layers,
            node_rank=int(data["node_rank"]) if data.get("node_rank") is not None else None,
            vllm_bin=str(data.get("vllm_bin", "vllm")),
            python_bin=str(data.get("python_bin", _default_python_bin(str(data.get("vllm_bin", "vllm"))))),
            working_directory=str(data["working_directory"]) if data.get("working_directory") else None,
            pythonpath=str(data["pythonpath"]) if data.get("pythonpath") else None,
            fabric_topology=str(data["fabric_topology"]) if data.get("fabric_topology") else None,
            extra_env={str(key): str(value) for key, value in dict(data.get("extra_env", {})).items()},
            cache_directories=tuple(str(item) for item in data.get("cache_directories", [])),
            connector=KvCacheConnector.from_json(dict(data["connector"])),
            cache_server=LmcacheServer.from_json(dict(data["cache_server"])) if data.get("cache_server") else None,
            lmcache_config=dict(data.get("lmcache_config", {})),
            extra_args=tuple(str(item) for item in data.get("extra_args", [])),
            cache_sharding=str(data.get("cache_sharding", data.get("kv_cache_sharding", "replicated"))),
            text_only=bool(data.get("text_only", False)),
        )
        _validate_deployment(deployment)
        return deployment

    @staticmethod
    def load(path: str | Path) -> "KvCacheDeployment":
        profile_path = Path(path)
        with profile_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("fabric_topology"):
            data["fabric_topology"] = _resolve_relative_profile_path(str(data["fabric_topology"]), base=profile_path.parent)
        return KvCacheDeployment.from_json(data)

    @property
    def is_pipeline(self) -> bool:
        return self.pipeline_parallel_size > 1


def kv_transfer_config(connector: KvCacheConnector) -> dict[str, Any]:
    if connector.connector_id == "none" or not connector.kv_connector:
        return {}
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
    env = _deployment_env(deployment)
    connector = _connector_with_server(deployment.connector, deployment.cache_server)
    fabric_nodes = _fabric_nodes(deployment)
    client_host = deployment.spark_node if deployment.host in {"0.0.0.0", "::"} else deployment.host
    rank = deployment.node_rank if deployment.node_rank is not None else 0
    vllm_plan = _vllm_node_plan(deployment, connector, node_rank=rank, env=env, fabric_nodes=fabric_nodes)
    return_plan: dict[str, Any] = {
        "format": KV_CACHE_PLAN_FORMAT,
        "deployment_id": deployment.deployment_id,
        "profile_id": deployment.profile_id,
        "state": "planned",
        "spark_node": deployment.spark_node,
        "entry_node": deployment.spark_node,
        "worker_nodes": list(deployment.worker_nodes),
        "logical_service_count": 1,
        "model_instance_count": 1,
        "listen_base_url": f"http://{deployment.host}:{deployment.http_port}",
        "openai_base_url": f"http://{client_host}:{deployment.http_port}",
        "tensor_parallel_size": deployment.tensor_parallel_size,
        "pipeline_parallel_size": deployment.pipeline_parallel_size,
        "layer_partition": list(deployment.layer_partition),
        "total_layers": deployment.total_layers,
        "cache_sharding": deployment.cache_sharding,
        "connector": {
            "connector_id": connector.connector_id,
            "install_packages": list(connector.install_packages),
            "install_args": list(connector.install_args),
            "wheel_dir": connector.wheel_dir,
            "kv_transfer_config": kv_transfer_config(connector),
        },
        "runtime": _runtime_plan(deployment),
        "notes": _plan_notes(deployment),
        "vllm": vllm_plan,
    }
    if deployment.is_pipeline:
        return_plan["vllm_nodes"] = [_vllm_node_plan(deployment, connector, node_rank=index, env=env, fabric_nodes=fabric_nodes) for index in range(deployment.pipeline_parallel_size)]
    if deployment.cache_server is not None:
        return_plan["cache_server"] = _lmcache_server_plan(deployment.cache_server, deployment)
    return return_plan


def write_launch_scripts(deployment: KvCacheDeployment, output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    plan = plan_deployment(deployment)
    scripts: dict[str, Path | dict[str, str]] = {
        "install": root / "00_install_kv_cache_deps.sh",
        "start_vllm": root / "start_vllm_cache.sh",
    }
    if deployment.cache_server is not None:
        scripts["start_cache_server"] = root / "start_lmcache_server.sh"
    fabric_nodes = _fabric_nodes(deployment)
    scripts["install"].write_text(_install_script(deployment, fabric_nodes), encoding="utf-8")  # type: ignore[union-attr]
    if deployment.is_pipeline:
        node_scripts: dict[str, str] = {}
        for node_plan in plan["vllm_nodes"]:
            node_id = str(node_plan["spark_node"])
            rank = int(node_plan["node_rank"])
            path = root / f"start_vllm_rank{rank}_{node_id}.sh"
            path.write_text(_start_script(node_plan, deployment), encoding="utf-8")
            path.chmod(0o755)
            node_scripts[node_id] = str(path)
            if rank == 0:
                scripts["start_vllm"] = path
        scripts["start_vllm_nodes"] = node_scripts
    else:
        scripts["start_vllm"].write_text(_start_script(plan["vllm"], deployment), encoding="utf-8")  # type: ignore[union-attr]
    if deployment.cache_server is not None:
        scripts["start_cache_server"].write_text(_start_script(plan["cache_server"], deployment), encoding="utf-8")  # type: ignore[union-attr]
    for value in scripts.values():
        if isinstance(value, Path):
            value.chmod(0o755)
    manifest = {
        "format": "ds4-vllm-kv-cache-launch-scripts-v1",
        "deployment_id": deployment.deployment_id,
        "scripts": {key: str(value) if isinstance(value, Path) else value for key, value in scripts.items()},
        "plan": plan,
    }
    (root / "kv_cache_launch_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def _deployment_env(deployment: KvCacheDeployment) -> dict[str, str]:
    env = dict(deployment.extra_env)
    if deployment.pythonpath:
        env["PYTHONPATH"] = deployment.pythonpath
    if deployment.is_pipeline and deployment.layer_partition:
        env.setdefault("VLLM_PP_LAYER_PARTITION", ",".join(str(item) for item in deployment.layer_partition))
    return env


def _vllm_node_plan(deployment: KvCacheDeployment, connector: KvCacheConnector, *, node_rank: int, env: dict[str, str], fabric_nodes: dict[str, TransferNode]) -> dict[str, Any]:
    if node_rank < 0 or node_rank >= deployment.pipeline_parallel_size:
        raise ValueError("node_rank is outside the pipeline stage range")
    spark_node = deployment.worker_nodes[node_rank] if deployment.is_pipeline else deployment.spark_node
    fabric_node = fabric_nodes.get(spark_node)
    rank_env = _env_for_rank(env, deployment, node_rank=node_rank, spark_node=spark_node, fabric_node=fabric_node)
    argv = _vllm_argv(deployment, connector, node_rank=node_rank, spark_node=spark_node, fabric_node=fabric_node)
    command = _format_env_command(rank_env, argv)
    node_plan = dict(
        _stage_plan(deployment, node_rank=node_rank, spark_node=spark_node, fabric_node=fabric_node),
        working_directory=_expand_rank_template(deployment.working_directory, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node) if deployment.working_directory else None,
        env=rank_env,
        argv=argv,
        command=command,
    )
    lmcache_config = _lmcache_config_plan(deployment, rank_env=rank_env, node_rank=node_rank, spark_node=spark_node, fabric_node=fabric_node)
    if lmcache_config is not None:
        node_plan["lmcache_config"] = lmcache_config
    return node_plan


def _stage_plan(deployment: KvCacheDeployment, *, node_rank: int, spark_node: str, fabric_node: TransferNode | None = None) -> dict[str, Any]:
    stage: dict[str, Any] = {"spark_node": spark_node, "node_rank": node_rank}
    if fabric_node is not None:
        stage.update({"fabric_host": fabric_node.fabric_host, "fabric_ip": fabric_node.fabric_ip})
    if deployment.layer_partition:
        start = sum(deployment.layer_partition[:node_rank])
        count = deployment.layer_partition[node_rank]
        stage.update({"stage_index": node_rank, "stage_count": deployment.pipeline_parallel_size, "layer_start": start, "layer_end": start + count, "layer_count": count})
    return stage


def _env_for_rank(env: dict[str, str], deployment: KvCacheDeployment, *, node_rank: int, spark_node: str, fabric_node: TransferNode | None = None) -> dict[str, str]:
    out = {key: _expand_rank_template(value, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node) for key, value in env.items()}
    if deployment.is_pipeline:
        out.setdefault("NODE_RANK", str(node_rank))
        out.setdefault("DS4_NODE_ID", spark_node)
        if deployment.connector.connector_id == "simple_cpu_offload":
            out.setdefault("VLLM_SIMPLE_KV_OFFLOAD_PERSIST_RANK", f"{spark_node}-r{node_rank}")
    return out


def _lmcache_config_plan(
    deployment: KvCacheDeployment,
    *,
    rank_env: dict[str, str],
    node_rank: int,
    spark_node: str,
    fabric_node: TransferNode | None = None,
) -> dict[str, Any] | None:
    if not deployment.lmcache_config:
        return None
    config_path = rank_env.get("LMCACHE_CONFIG_FILE")
    if not config_path:
        raise ValueError("lmcache_config requires LMCACHE_CONFIG_FILE in extra_env")
    return {
        "path": config_path,
        "data": _expand_rank_data(deployment.lmcache_config, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node),
    }


def _expand_rank_data(data: Any, *, spark_node: str, node_rank: int, fabric_node: TransferNode | None = None) -> Any:
    if isinstance(data, str):
        return _expand_rank_template(data, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node)
    if isinstance(data, list):
        return [_expand_rank_data(item, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node) for item in data]
    if isinstance(data, dict):
        return {str(key): _expand_rank_data(value, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node) for key, value in data.items()}
    return data


def _vllm_argv(deployment: KvCacheDeployment, connector: KvCacheConnector, *, node_rank: int = 0, spark_node: str | None = None, fabric_node: TransferNode | None = None) -> list[str]:
    spark_node = spark_node or deployment.spark_node
    vllm_bin = _expand_rank_template(deployment.vllm_bin, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node)
    model_id = _expand_rank_template(deployment.model_id, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node)
    argv = _vllm_serve_prefix(vllm_bin) + [model_id]
    if not deployment.is_pipeline or node_rank == 0:
        argv.extend(["--host", deployment.host, "--port", str(deployment.http_port)])
    argv.extend([
        "--tensor-parallel-size",
        str(deployment.tensor_parallel_size),
    ])
    if deployment.is_pipeline:
        argv.extend([
            "--pipeline-parallel-size",
            str(deployment.pipeline_parallel_size),
            "--nnodes",
            str(deployment.pipeline_parallel_size),
            "--node-rank",
            str(node_rank),
            "--master-addr",
            str(deployment.master_addr or deployment.spark_node),
            "--master-port",
            str(deployment.master_port or 29500),
        ])
    transfer = kv_transfer_config(connector)
    if transfer:
        argv.extend(["--kv-transfer-config", json.dumps(transfer, sort_keys=True)])
    if deployment.served_model_name:
        argv.extend(["--served-model-name", _expand_rank_template(deployment.served_model_name, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node)])
    if deployment.text_only:
        argv.append("--language-model-only")
    extra_args = tuple(_expand_rank_template(item, spark_node=spark_node, node_rank=node_rank, fabric_node=fabric_node) for item in deployment.extra_args)
    argv.extend(_dedupe_args(extra_args, present=set(item for item in argv if item.startswith("--"))))
    if deployment.is_pipeline and node_rank != 0 and "--headless" not in argv:
        argv.append("--headless")
    return argv


def _vllm_serve_prefix(vllm_bin: str) -> list[str]:
    name = Path(vllm_bin).name
    if name.startswith("python"):
        return [vllm_bin, "-m", "vllm.entrypoints.cli.main", "serve"]
    return [vllm_bin, "serve"]


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


def _plan_notes(deployment: KvCacheDeployment) -> list[str]:
    if deployment.is_pipeline:
        return [
            "Layer-pipeline KV cache: each Spark owns and stores only its local stage cache/state shard.",
            "spark0 is the OpenAI/API ingress; nonzero ranks are vLLM headless workers.",
            "Use the DS4 queue compute-domain lease above vLLM when multiple resident pipelines share the same Sparks.",
            "If total_layers is provided and no tuned partition is present, the planner uses a simple layers/N split; recipes may override with layer_partition or layer_partition_by_node.",
        ]
    return [
        "Single-service KV cache: one vLLM serving lane owns model execution, batching, and external KV load/store.",
        "Tensor parallel workers may span multiple Sparks, but this is not a prefiller/decoder split.",
        "Use the queue readiness stage and external KV connector to prepare reusable prompt skeletons.",
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


def _validate_lmcache_server(server: LmcacheServer) -> None:
    if server.port <= 0 or server.http_port <= 0:
        raise ValueError("LMCache server ports must be positive")
    if server.l1_size_gb <= 0:
        raise ValueError("LMCache l1_size_gb must be positive")
    if server.chunk_size <= 0:
        raise ValueError("LMCache chunk_size must be positive")


def _validate_deployment(deployment: KvCacheDeployment) -> None:
    if deployment.pipeline_parallel_size > 1:
        if len(deployment.worker_nodes) != deployment.pipeline_parallel_size:
            raise ValueError("pipeline_parallel_size must match worker_nodes length for pipeline deployments")
        if deployment.layer_partition and len(deployment.layer_partition) != deployment.pipeline_parallel_size:
            raise ValueError("layer_partition length must match pipeline_parallel_size")
        if any(item <= 0 for item in deployment.layer_partition):
            raise ValueError("layer_partition entries must be positive")
        if deployment.total_layers is not None and deployment.layer_partition and sum(deployment.layer_partition) != deployment.total_layers:
            raise ValueError("layer_partition must sum to total_layers")
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


def _default_connector_name(connector_id: str) -> str:
    if connector_id == "none":
        return ""
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


def _fabric_nodes(deployment: KvCacheDeployment) -> dict[str, TransferNode]:
    if not deployment.fabric_topology:
        return {}
    topology = TransferTopology.load(deployment.fabric_topology)
    nodes: dict[str, TransferNode] = {}
    for node_id in deployment.worker_nodes:
        nodes[node_id] = topology.get_node(node_id)
    return nodes


def _expand_rank_template(value: str, *, spark_node: str, node_rank: int, fabric_node: TransferNode | None = None) -> str:
    if ("{fabric_ip}" in value or "{fabric_host}" in value) and fabric_node is None:
        raise ValueError("fabric topology is required to expand fabric templates")
    return (
        value.replace("{node}", spark_node)
        .replace("{spark_node}", spark_node)
        .replace("{node_rank}", str(node_rank))
        .replace("{rank}", str(node_rank))
        .replace("{fabric_host}", fabric_node.fabric_host if fabric_node is not None else "")
        .replace("{fabric_ip}", fabric_node.fabric_ip if fabric_node is not None else "")
    )


def _install_script(deployment: KvCacheDeployment, fabric_nodes: dict[str, TransferNode]) -> str:
    packages = " ".join(shlex.quote(item) for item in deployment.connector.install_packages)
    fabric_node = fabric_nodes.get(deployment.spark_node)
    workdir = _expand_rank_template(deployment.working_directory or ".", spark_node=deployment.spark_node, node_rank=0, fabric_node=fabric_node)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "cd " + shlex.quote(workdir),
    ]
    if deployment.connector.connector_id == "lmcache_mp" and packages:
        wheel_dir = deployment.connector.wheel_dir or "/tmp/ds4_lmcache_wheels"
        wheel_glob = _lmcache_wheel_glob(deployment.connector.install_packages)
        wheel_argv = [deployment.python_bin, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps", "--wheel-dir", wheel_dir]
        wheel_argv.extend(deployment.connector.install_packages)
        lines.append("mkdir -p " + shlex.quote(wheel_dir))
        lines.append(_format_env_command(_env_for_rank(deployment.extra_env, deployment, node_rank=0, spark_node=deployment.spark_node, fabric_node=fabric_node), wheel_argv))
        lines.append("wheel=$(find " + shlex.quote(wheel_dir) + " -maxdepth 1 -name " + shlex.quote(wheel_glob) + " -print -quit)")
        lines.append('if [ -z "${wheel}" ]; then echo "[ds4-kvcache] LMCache wheel not found" >&2; exit 2; fi')
        install_argv = [deployment.python_bin, "-m", "pip", "install", "--no-deps"]
        lines.append(_format_env_command(_env_for_rank(deployment.extra_env, deployment, node_rank=0, spark_node=deployment.spark_node, fabric_node=fabric_node), install_argv) + ' "${wheel}"')
    elif packages:
        argv = [deployment.python_bin, "-m", "pip", "install", "--upgrade"]
        argv.extend(deployment.connector.install_args)
        argv.extend(deployment.connector.install_packages)
        lines.append(_format_env_command(_env_for_rank(deployment.extra_env, deployment, node_rank=0, spark_node=deployment.spark_node, fabric_node=fabric_node), argv))
    else:
        lines.append("echo '[ds4-kvcache] no connector packages requested'")
    for path in deployment.cache_directories:
        lines.append("mkdir -p " + shlex.quote(_expand_rank_template(path, spark_node=deployment.spark_node, node_rank=0, fabric_node=fabric_node)))
    return "\n".join(lines) + "\n"


def _resolve_relative_profile_path(value: str, *, base: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    candidate = (base / path).resolve()
    if candidate.exists():
        return str(candidate)
    candidate = (Path.cwd() / path).resolve()
    if candidate.exists():
        return str(candidate)
    return str((base / path).resolve())


def _lmcache_wheel_glob(packages: tuple[str, ...]) -> str:
    for package in packages:
        if package.startswith("lmcache=="):
            return "lmcache-" + package.split("==", 1)[1] + "-*.whl"
    return "lmcache-*.whl"


def _default_python_bin(vllm_bin: str) -> str:
    if "/" not in vllm_bin:
        return "python3"
    return vllm_bin.rsplit("/", 1)[0] + "/python"


def _starts_with_env_assignment(command: str) -> bool:
    first = command.split(" ", 1)[0]
    return "=" in first and not first.startswith("/") and not first.startswith("./")


def _start_script(vllm_plan: dict[str, Any], deployment: KvCacheDeployment) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
    ]
    workdir = vllm_plan.get("working_directory") or deployment.working_directory
    if workdir:
        lines.append("cd " + shlex.quote(str(workdir)))
    lines.extend(_lmcache_config_script(vllm_plan))
    if vllm_plan.get("env") or _starts_with_env_assignment(vllm_plan["command"]):
        lines.append("exec env " + vllm_plan["command"])
    else:
        lines.append("exec " + vllm_plan["command"])
    return "\n".join(lines) + "\n"


def _lmcache_config_script(vllm_plan: dict[str, Any]) -> list[str]:
    config = vllm_plan.get("lmcache_config")
    if not isinstance(config, dict):
        return []
    config_path = str(config["path"])
    data = dict(config["data"])
    lines: list[str] = []
    parent = str(Path(config_path).parent)
    if parent and parent != ".":
        lines.append("mkdir -p " + shlex.quote(parent))
    local_disk = data.get("local_disk")
    if isinstance(local_disk, str) and local_disk:
        for item in local_disk.split(","):
            path = item.strip()
            if path:
                lines.append("mkdir -p " + shlex.quote(path))
    lines.append("cat > " + shlex.quote(config_path) + " <<'DS4_LMCACHE_CONFIG_EOF'")
    lines.extend(_format_yaml(data).splitlines())
    lines.append("DS4_LMCACHE_CONFIG_EOF")
    return lines


def _format_yaml(data: dict[str, Any]) -> str:
    return "\n".join(_format_yaml_lines(data, 0)) + "\n"


def _format_yaml_lines(data: dict[str, Any], indent: int) -> list[str]:
    lines: list[str] = []
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.extend(_format_yaml_lines(value, indent + 2))
        elif isinstance(value, list):
            lines.append(f"{pad}{key}:")
            for item in value:
                lines.append(f"{pad}  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{pad}{key}: {_yaml_scalar(value)}")
    return lines


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def _deployment_layer_partition(data: dict[str, Any], *, worker_nodes: tuple[str, ...], stage_count: int, total_layers: int | None) -> tuple[int, ...]:
    by_node = data.get("layer_partition_by_node")
    if by_node is not None:
        if not isinstance(by_node, dict):
            raise ValueError("layer_partition_by_node must be an object")
        missing = [node for node in worker_nodes if node not in by_node]
        if missing:
            raise ValueError(f"layer_partition_by_node missing nodes: {missing}")
        extra = [node for node in by_node if node not in set(worker_nodes)]
        if extra:
            raise ValueError(f"layer_partition_by_node references nodes outside worker_nodes: {extra}")
        return tuple(int(by_node[node]) for node in worker_nodes)
    parsed = _parse_layer_partition(data.get("layer_partition", data.get("pipeline_layer_partition")))
    if parsed:
        return parsed
    if total_layers is not None and stage_count > 1:
        return even_layer_partition(total_layers, stage_count)
    return parsed


def _parse_layer_partition(raw: Any) -> tuple[int, ...]:
    if raw is None or raw == "":
        return ()
    if isinstance(raw, str):
        return tuple(int(piece.strip()) for piece in raw.split(",") if piece.strip())
    if isinstance(raw, list):
        return tuple(int(item) for item in raw)
    raise ValueError("layer_partition must be a comma string or list")
