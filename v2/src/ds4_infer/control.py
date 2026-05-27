from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
from typing import Any
from urllib.parse import urlencode

from .profiles import ProfileRegistry
from .topology import SparkTopology

REMOTE_TRIM_SCRIPT = r'''
import json,sys,urllib.error,urllib.request
base_url,path,query = sys.argv[1:4]
url = base_url.rstrip("/") + path + ("?" + query if query else "")
req = urllib.request.Request(url,data=b"",method="POST")
try:
    with urllib.request.urlopen(req,timeout=int(sys.argv[4])) as response:
        body = response.read().decode("utf-8",errors="replace")
        status = getattr(response,"status",200)
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8",errors="replace")
    print(json.dumps({"ok":False,"status":exc.code,"body":body},sort_keys=True))
    raise SystemExit(0)
try:
    parsed = json.loads(body) if body.strip() else None
except json.JSONDecodeError:
    parsed = None
print(json.dumps({"ok":200 <= status < 300,"status":status,"body":body,"json":parsed},sort_keys=True))
'''


def trim_spark_memory(
    *,
    node_id: str,
    topology_path: str | Path,
    profiles_dir: str | Path,
    contracts_dir: str | Path,
    profile_id: str | None = None,
    base_url: str | None = None,
    execute: bool = False,
    timeout_s: int = 60,
    mode: str = "abort",
    reset_external: bool = True,
    release_offload_memory: bool = True,
    malloc_trim: bool = True,
    resume: bool = True,
    command_runner: Any = subprocess.run,
) -> dict[str, Any]:
    plan = trim_spark_memory_plan(
        node_id=node_id,
        topology_path=topology_path,
        profiles_dir=profiles_dir,
        contracts_dir=contracts_dir,
        profile_id=profile_id,
        base_url=base_url,
        timeout_s=timeout_s,
        mode=mode,
        reset_external=reset_external,
        release_offload_memory=release_offload_memory,
        malloc_trim=malloc_trim,
        resume=resume,
    )
    if not execute:
        return plan
    return _execute_trim_plan(plan, timeout_s=timeout_s, command_runner=command_runner)


def _execute_trim_plan(plan: dict[str, Any], *, timeout_s: int, command_runner: Any) -> dict[str, Any]:
    completed = command_runner(
        plan["transport"]["argv"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s + 15,
        check=False,
    )
    result = {
        "format": "ds4-spark-trim-memory-result-v1",
        "ok": False,
        "execute": True,
        "node_id": plan["node_id"],
        "ingress_node_id": plan["ingress_node_id"],
        "profile_id": plan.get("profile_id"),
        "runtime_contract_id": plan.get("runtime_contract_id"),
        "endpoint": plan["endpoint"],
        "transport": {
            "argv": plan["transport"]["argv"],
            "returncode": int(completed.returncode),
            "stderr_tail": str(completed.stderr)[-4000:],
            "stdout_tail": str(completed.stdout)[-4000:],
        },
    }
    if int(completed.returncode) != 0:
        result["error"] = "ssh trim command failed"
        return result
    remote = _parse_remote_response(str(completed.stdout))
    result["response"] = remote
    result["ok"] = bool(remote.get("ok"))
    return result


def trim_spark_memory_plan(
    *,
    node_id: str,
    topology_path: str | Path,
    profiles_dir: str | Path,
    contracts_dir: str | Path,
    profile_id: str | None = None,
    base_url: str | None = None,
    timeout_s: int = 60,
    mode: str = "abort",
    reset_external: bool = True,
    release_offload_memory: bool = True,
    malloc_trim: bool = True,
    resume: bool = True,
) -> dict[str, Any]:
    if mode not in {"abort", "wait"}:
        raise ValueError("trim-memory mode must be abort or wait")
    target = _resolve_trim_target(
        node_id=node_id,
        topology_path=topology_path,
        profiles_dir=profiles_dir,
        contracts_dir=contracts_dir,
        profile_id=profile_id,
        base_url=base_url,
    )
    query = _trim_query(
        mode=mode,
        reset_external=reset_external,
        release_offload_memory=release_offload_memory,
        malloc_trim=malloc_trim,
        resume=resume,
    )
    argv = _transport_argv(
        target["ingress_node_id"],
        target["endpoint_base_url"],
        target["endpoint_path"],
        query,
        timeout_s,
    )
    return _plan_payload(node_id=node_id, target=target, query=query, argv=argv)


def _resolve_trim_target(
    *,
    node_id: str,
    topology_path: str | Path,
    profiles_dir: str | Path,
    contracts_dir: str | Path,
    profile_id: str | None,
    base_url: str | None,
) -> dict[str, Any]:
    topology = SparkTopology.load(topology_path)
    registry = ProfileRegistry.load(profiles_dir)
    node = _node(topology, node_id)
    selected_profile_id = (
        profile_id
        or _trim_default_profile(topology, node_id)
        or _single_resident_profile(node_id, node.resident_profiles, base_url)
    )
    profile = registry.get(selected_profile_id) if selected_profile_id else None
    contract_id = profile.runtime_contract_id if profile is not None else None
    if base_url is None and profile is not None and contract_id is None:
        raise ValueError(f"profile {profile.profile_id} has no runtime_contract_id; pass --base-url or add a runtime contract")
    if base_url is None and contract_id is None:
        raise ValueError("trim-memory needs a resident profile, --profile-id, or --base-url")
    contract = _load_contract(contracts_dir, contract_id) if contract_id is not None else None
    endpoint_path = str((contract or {}).get("vllm", {}).get("trim_endpoint", "/v1/trim_memory"))
    ingress_node_id = _ingress_node_id(topology, contract or {}, selected_profile_id, node_id)
    endpoint_base_url = base_url or _contract_base_url(contract or {}, node_id=node_id, ingress_node_id=ingress_node_id)
    return {
        "profile_id": selected_profile_id,
        "runtime_contract_id": contract_id,
        "ingress_node_id": ingress_node_id,
        "endpoint_base_url": endpoint_base_url,
        "endpoint_path": endpoint_path,
    }


def _trim_query(*, mode: str, reset_external: bool, release_offload_memory: bool, malloc_trim: bool, resume: bool) -> str:
    return urlencode(
        {
            "mode": mode,
            "reset_external": _bool_query(reset_external),
            "release_offload_memory": _bool_query(release_offload_memory),
            "malloc_trim": _bool_query(malloc_trim),
            "resume": _bool_query(resume),
        }
    )


def _transport_argv(ingress_node_id: str, endpoint_base_url: str, endpoint_path: str, query: str, timeout_s: int) -> list[str]:
    remote_args = [endpoint_base_url, endpoint_path, query, str(timeout_s)]
    remote_command = "python3 -c " + shlex.quote(REMOTE_TRIM_SCRIPT) + " " + " ".join(shlex.quote(arg) for arg in remote_args)
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        ingress_node_id,
        remote_command,
    ]


def _plan_payload(*, node_id: str, target: dict[str, Any], query: str, argv: list[str]) -> dict[str, Any]:
    return {
        "format": "ds4-spark-trim-memory-plan-v1",
        "ok": True,
        "execute": False,
        "node_id": node_id,
        "ingress_node_id": target["ingress_node_id"],
        "profile_id": target["profile_id"],
        "runtime_contract_id": target["runtime_contract_id"],
        "endpoint": {
            "method": "POST",
            "base_url": target["endpoint_base_url"],
            "path": target["endpoint_path"],
            "query": query,
        },
        "transport": {
            "kind": "ssh-localhost-http",
            "argv": argv,
        },
    }


def _node(topology: SparkTopology, node_id: str):
    for node in topology.nodes:
        if node.node_id == node_id:
            return node
    raise ValueError(f"unknown spark node: {node_id}")


def _single_resident_profile(node_id: str, resident_profiles: tuple[str, ...], base_url: str | None) -> str | None:
    if len(resident_profiles) == 1:
        return resident_profiles[0]
    if base_url is not None and not resident_profiles:
        return None
    if not resident_profiles:
        raise ValueError(f"{node_id} has no resident profile; pass --profile-id or --base-url")
    raise ValueError(f"{node_id} has multiple resident profiles; pass --profile-id")


def _trim_default_profile(topology: SparkTopology, node_id: str) -> str | None:
    raw = topology.routing_policy.get("trim_default_profiles_by_node", {})
    if not isinstance(raw, dict):
        raise ValueError("routing_policy.trim_default_profiles_by_node must be an object")
    value = raw.get(node_id)
    return str(value) if value else None


def _load_contract(contracts_dir: str | Path, contract_id: str | None) -> dict[str, Any]:
    if contract_id is None:
        return {}
    path = Path(contracts_dir) / f"{contract_id}.json"
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("format") != "ds4-runtime-contract-v1":
        raise ValueError(f"unsupported runtime contract format in {path}")
    return data


def _contract_base_url(contract: dict[str, Any], *, node_id: str, ingress_node_id: str) -> str:
    overrides = contract.get("launch",{}).get("node_overrides",{})
    if isinstance(overrides, dict):
        override = overrides.get(node_id) or overrides.get(ingress_node_id)
        if isinstance(override, dict) and override.get("api_base_url"):
            return str(override["api_base_url"])
    launch = contract.get("launch",{})
    if launch.get("api_base_url"):
        return str(launch["api_base_url"])
    host = str(launch.get("host","127.0.0.1"))
    port = int(launch["port"])
    return f"http://{host}:{port}"


def _ingress_node_id(topology: SparkTopology, contract: dict[str, Any], profile_id: str | None, node_id: str) -> str:
    head_node = contract.get("launch",{}).get("head_node")
    if head_node:
        return str(head_node)
    if profile_id is not None and profile_id in topology.profile_node_groups:
        return topology.profile_group_ingress.get(profile_id,topology.profile_node_groups[profile_id][0])
    return node_id


def _bool_query(value: bool) -> str:
    return "true" if value else "false"


def _parse_remote_response(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        return {"ok": False, "error": "empty trim response"}
    try:
        return json.loads(text.splitlines()[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": "trim response was not JSON", "body": text[-4000:]}
