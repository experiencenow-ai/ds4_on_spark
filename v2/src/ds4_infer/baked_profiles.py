from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any


LOCK_FORMAT = "ds4-vllm-engine-lock-v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(raw: str, base: Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


def create_engine_lock(
    *,
    profile_name: str,
    runtime_contract_path: Path,
    topology_path: Path | None,
    service_id: str | None,
    ds4_repo: Path,
    vllm_repo: Path | None,
    model_path: str | None = None,
    served_model_name: str | None = None,
    node_ids: list[str] | None = None,
    layer_partition: list[int] | None = None,
    pipeline_parallel_size: int | None = None,
    tensor_parallel_size: int | None = None,
    arg_sets: dict[str, str] | None = None,
    arg_drops: list[str] | None = None,
    env_sets: dict[str, str] | None = None,
    expected_banner: dict[str, str] | None = None,
    cache_root: str | None = None,
    cache_root_base: str = "/opt/ds4/vllm_cache",
    semantic_preset: str = "none",
    allow_dirty: bool = False,
    ds4_commit: str | None = None,
    vllm_commit: str | None = None,
) -> dict[str, Any]:
    contract = load_json(runtime_contract_path)
    service = _find_service(topology_path, service_id) if topology_path is not None and service_id is not None else {}
    launch = contract.get("launch") if isinstance(contract.get("launch"), dict) else {}
    model = contract.get("model") if isinstance(contract.get("model"), dict) else {}
    pipeline = contract.get("pipeline") if isinstance(contract.get("pipeline"), dict) else {}
    args = [str(item) for item in launch.get("args", [])]
    for flag in arg_drops or []:
        args = drop_arg(args, flag)
    for flag, value in (arg_sets or {}).items():
        args = set_arg(args, flag, value)
    pp_size = int(pipeline_parallel_size or service.get("pipeline_parallel_size") or pipeline.get("pipeline_parallel_size") or 1)
    tp_size = int(tensor_parallel_size or service.get("tensor_parallel_size") or pipeline.get("tensor_parallel_size") or 1)
    args = set_arg(args, "--pipeline-parallel-size", str(pp_size))
    args = set_arg(args, "--tensor-parallel-size", str(tp_size))
    partition = layer_partition or _as_int_list(service.get("layer_partition")) or _as_int_list(pipeline.get("layer_partition"))
    if not partition:
        raise ValueError("layer partition is required")
    nodes = node_ids or _as_str_list(service.get("node_ids")) or _as_str_list(contract.get("required_nodes"))
    if not nodes:
        raise ValueError("node list is required")
    model_id = str(model_path or model.get("model_id") or service.get("model_id") or "")
    if not model_id:
        raise ValueError("model path/model id is required")
    served_name = str(served_model_name or model.get("served_model_name") or service.get("served_model_name") or model_id)
    env = {str(k): str(v) for k, v in (env_sets or {}).items()}
    ds4_rev = ds4_commit or git_commit(ds4_repo)
    vllm_rev = vllm_commit or (git_commit(vllm_repo) if vllm_repo is not None else "")
    dirty = {
        "ds4": False if ds4_commit is not None else git_dirty(ds4_repo),
        "vllm": False if vllm_commit is not None else (git_dirty(vllm_repo) if vllm_repo is not None else False),
    }
    if not allow_dirty and any(dirty.values()):
        dirty_names = ", ".join(name for name, value in dirty.items() if value)
        raise ValueError(f"refusing to bake from dirty repo(s): {dirty_names}")
    parallelism = {
        "pipeline_parallel_size": pp_size,
        "tensor_parallel_size": tp_size,
        "expert_parallel": "--enable-expert-parallel" in args,
        "layer_partition": partition,
        "stage_start_layers": stage_start_layers(partition),
        "node_ids": nodes,
    }
    identity = {
        "profile_name": profile_name,
        "ds4_commit": ds4_rev,
        "vllm_commit": vllm_rev,
        "model_path": model_id,
        "served_model_name": served_name,
        "parallelism": parallelism,
        "vllm_args": args,
        "env": env,
        "expected_banner": expected_banner or {},
    }
    profile_hash = stable_hash(identity)
    if cache_root is None:
        cache_root = str(Path(cache_root_base) / f"{profile_name}_{profile_hash[:12]}")
    env = dict(env)
    env["VLLM_CACHE_ROOT"] = cache_root
    lock = {
        "format": LOCK_FORMAT,
        "profile_name": profile_name,
        "profile_hash": profile_hash,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repos": {
            "ds4_commit": ds4_rev,
            "vllm_commit": vllm_rev,
            "ds4_dirty": dirty["ds4"],
            "vllm_dirty": dirty["vllm"],
        },
        "model": {
            "model_path": model_id,
            "served_model_name": served_name,
            "runtime_contract": str(runtime_contract_path),
        },
        "parallelism": parallelism,
        "vllm_args": args,
        "env": env,
        "expected_banner": expected_banner or {},
        "semantic_gates": semantic_gates(semantic_preset),
        "launch": {
            "host": str(launch.get("host", "0.0.0.0")),
            "port": int(launch.get("port", 0) or 0),
            "master_addr": str(launch.get("master_addr", nodes[0])),
            "master_port": int(launch.get("master_port", 0) or 0),
            "rank_commands": rank_commands(nodes=nodes, model_path=model_id, args=args, env=env),
        },
    }
    lock["lock_sha256"] = lock_sha256(lock)
    return lock


def validate_lock(lock: dict[str, Any], *, current_env: dict[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    if lock.get("format") != LOCK_FORMAT:
        errors.append(f"format is {lock.get('format')!r}, expected {LOCK_FORMAT!r}")
    expected_hash = lock.get("lock_sha256")
    if expected_hash != lock_sha256(lock):
        errors.append("lock_sha256 does not match lock contents")
    parallelism = lock.get("parallelism") if isinstance(lock.get("parallelism"), dict) else {}
    partition = _as_int_list(parallelism.get("layer_partition"))
    nodes = _as_str_list(parallelism.get("node_ids"))
    pp_size = int(parallelism.get("pipeline_parallel_size") or 0)
    if pp_size <= 0:
        errors.append("pipeline_parallel_size must be positive")
    if len(nodes) != pp_size:
        errors.append(f"node_ids length {len(nodes)} != pipeline_parallel_size {pp_size}")
    if len(partition) != pp_size:
        errors.append(f"layer_partition length {len(partition)} != pipeline_parallel_size {pp_size}")
    if any(item <= 0 for item in partition):
        errors.append("layer_partition entries must be positive")
    args = [str(item) for item in lock.get("vllm_args", [])]
    for flag in ("--pipeline-parallel-size", "--tensor-parallel-size", "--max-model-len"):
        if flag not in args:
            errors.append(f"missing required vLLM arg {flag}")
    env = lock.get("env") if isinstance(lock.get("env"), dict) else {}
    cache_root = str(env.get("VLLM_CACHE_ROOT") or "")
    if not cache_root:
        errors.append("env.VLLM_CACHE_ROOT is required")
    if current_env is not None:
        for key, value in env.items():
            actual = current_env.get(str(key))
            if actual is not None and actual != str(value):
                errors.append(f"current env {key}={actual!r} differs from lock value {value!r}")
    return errors


def verify_repos(lock: dict[str, Any], *, ds4_repo: Path | None, vllm_repo: Path | None) -> list[str]:
    errors: list[str] = []
    repos = lock.get("repos") if isinstance(lock.get("repos"), dict) else {}
    if ds4_repo is not None:
        expected = str(repos.get("ds4_commit") or "")
        actual = git_commit(ds4_repo)
        if expected and actual != expected:
            errors.append(f"DS4 commit {actual} != locked {expected}")
    if vllm_repo is not None:
        expected = str(repos.get("vllm_commit") or "")
        actual = git_commit(vllm_repo)
        if expected and actual != expected:
            errors.append(f"vLLM commit {actual} != locked {expected}")
    return errors


def write_lock(lock: dict[str, Any], output: Path) -> Path:
    path = output if output.suffix == ".json" else output / "engine.lock.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_rank_files(lock: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    nodes = lock["parallelism"]["node_ids"]
    env = {str(k): str(v) for k, v in lock.get("env", {}).items()}
    commands = lock["launch"]["rank_commands"]
    for rank, node_id in enumerate(nodes):
        rank_env = dict(env)
        rank_env["NODE_RANK"] = str(rank)
        rank_env["DS4_NODE_ID"] = str(node_id)
        env_lines = [f"{key}={shlex.quote(value)}" for key, value in sorted(rank_env.items())]
        (output_dir / f"rank_{rank}.env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        (output_dir / f"rank_{rank}.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + commands[rank] + "\n", encoding="utf-8")


def set_arg(args: list[str], flag: str, value: str) -> list[str]:
    values = list(args)
    if flag in values:
        index = values.index(flag)
        if index + 1 >= len(values):
            values.append(str(value))
        else:
            values[index + 1] = str(value)
        return values
    values.extend([flag, str(value)])
    return values


def drop_arg(args: list[str], flag: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(args):
        if args[index] == flag:
            index += 2 if index + 1 < len(args) and not args[index + 1].startswith("--") else 1
            continue
        values.append(args[index])
        index += 1
    return values


def parse_set_arg(raw: str) -> tuple[str, str]:
    flag, sep, value = raw.partition("=")
    if sep == "" or not flag.startswith("--"):
        raise ValueError(f"--set-arg expects --flag=value, got {raw!r}")
    return flag, value


def parse_key_value(raw: str) -> tuple[str, str]:
    key, sep, value = raw.partition("=")
    if sep == "" or key == "":
        raise ValueError(f"expected KEY=VALUE, got {raw!r}")
    return key, value


def parse_csv_ints(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_csv_strings(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def stage_start_layers(partition: list[int]) -> list[int]:
    starts: list[int] = []
    current = 0
    for count in partition:
        starts.append(current)
        current += int(count)
    return starts


def semantic_gates(preset: str) -> list[dict[str, Any]]:
    if preset == "none":
        return []
    if preset != "dsv4-basic":
        raise ValueError(f"unknown semantic preset {preset!r}")
    return [
        {"prompt": "The capital of France is", "max_tokens": 1, "temperature": 0, "logprobs": 10},
        {"prompt": "Answer only the number. What is 2+2?\n", "max_tokens": 1, "temperature": 0, "logprobs": 10},
    ]


def rank_commands(*, nodes: list[str], model_path: str, args: list[str], env: dict[str, str]) -> list[str]:
    env_prefix = " ".join(f"{key}={shlex.quote(str(value))}" for key, value in sorted(env.items()))
    argv = " ".join(shlex.quote(item) for item in ["vllm", "serve", model_path, *args])
    return [f"NODE_RANK={rank} DS4_NODE_ID={shlex.quote(node)} {env_prefix} {argv}" for rank, node in enumerate(nodes)]


def git_commit(repo: Path | None) -> str:
    if repo is None:
        return ""
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def git_dirty(repo: Path | None) -> bool:
    if repo is None:
        return False
    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout.strip() != ""


def stable_hash(data: Any) -> str:
    return hashlib.sha256(_canonical(data).encode("utf-8")).hexdigest()


def lock_sha256(lock: dict[str, Any]) -> str:
    clone = copy.deepcopy(lock)
    clone.pop("lock_sha256", None)
    return stable_hash(clone)


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _find_service(topology_path: Path, service_id: str) -> dict[str, Any]:
    topology = load_json(topology_path)
    routing = topology.get("routing_policy") if isinstance(topology.get("routing_policy"), dict) else {}
    services = routing.get("pipeline_services") if isinstance(routing.get("pipeline_services"), dict) else {}
    service = services.get(service_id)
    if not isinstance(service, dict):
        raise ValueError(f"service {service_id!r} not found in {topology_path}")
    return service


def _as_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    return [int(item) for item in value]


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
