#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import posixpath
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


DEFAULT_TOPOLOGY = "sparknetwork.json"
DEFAULT_TARGET = "ds4"
DEFAULT_REMOTE_REPO = "src/ds4"
DEFAULT_DEPLOY_ROOT_NAME = "ds4-deploy"
DEFAULT_PORT = 24140
DEFAULT_PARALLEL = 16
DEFAULT_CHUNK_MIB = 64


@dataclass(frozen=True)
class Node:
    node_id: str
    user: str
    ssh_alias: str


@dataclass(frozen=True)
class DeployPath:
    node: Node
    path: str


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


Runner = Callable[[Sequence[str], float | None], CommandResult]


def utc_run_id() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_runner(command: Sequence[str], timeout_seconds: float | None = None) -> CommandResult:
    start = time.monotonic()
    proc = subprocess.run(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)


def load_topology(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def topology_nodes(topology: dict) -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    for item in topology.get("nodes", []):
        node_id = str(item["id"])
        nodes[node_id] = Node(node_id=node_id, user=str(item.get("user") or node_id), ssh_alias=str(item.get("ssh_alias") or node_id))
    return nodes


def ring_order(topology: dict) -> list[str]:
    return [str(item) for item in topology["ring_200g"]["order"]]


def direct_neighbors(topology: dict, left: str, right: str) -> bool:
    for entry in topology["ring_200g"]["links"]:
        a = entry["a"]["node"]
        b = entry["b"]["node"]
        if (a == left and b == right) or (a == right and b == left):
            return True
    return False


def validate_nodes(topology: dict, requested: Sequence[str]) -> list[Node]:
    nodes = topology_nodes(topology)
    missing = [node for node in requested if node not in nodes]
    if missing:
        raise ValueError("unknown Spark node(s): " + ", ".join(missing))
    return [nodes[node] for node in requested]


def validate_ring_hops(topology: dict, requested: Sequence[str]) -> None:
    if len(requested) < 2:
        return
    order = ring_order(topology)
    for left, right in zip(requested, requested[1:]):
        if not direct_neighbors(topology, left, right):
            raise ValueError("%s and %s are not direct 200G neighbors; use a contiguous hop list from %s" % (left, right, " -> ".join(order)))


def remote_home(node: Node) -> str:
    return "/home/%s" % node.user


def remote_repo_path(node: Node, remote_repo: str) -> str:
    if remote_repo.startswith("/"):
        return remote_repo
    return posixpath.join(remote_home(node), remote_repo)


def deploy_dir(node: Node, deploy_root_name: str, run_id: str) -> str:
    return posixpath.join(remote_home(node), deploy_root_name, run_id)


def deploy_path(node: Node, deploy_root_name: str, run_id: str, target: str) -> DeployPath:
    return DeployPath(node=node, path=posixpath.join(deploy_dir(node, deploy_root_name, run_id), target))


def ssh_command(node: Node, script: str) -> list[str]:
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", node.ssh_alias, "sh -lc " + shlex.quote(script)]


def shell_join(parts: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def run_or_raise(runner: Runner, command: Sequence[str], timeout_seconds: float | None = None) -> CommandResult:
    result = runner(command, timeout_seconds)
    print("$ " + shell_join(command))
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    print("rc=%d elapsed_seconds=%.3f" % (result.returncode, result.elapsed_seconds))
    if result.returncode != 0:
        raise RuntimeError("command failed: " + shell_join(command))
    return result


def best_effort_existing_hash(runner: Runner, node: Node, remote_file: str, timeout_seconds: float) -> str:
    script = "if [ -f %s ]; then sha256sum %s | awk '{print $1}'; else printf missing; fi" % (shlex.quote(remote_file), shlex.quote(remote_file))
    result = runner(ssh_command(node, script), timeout_seconds)
    if result.returncode != 0:
        return "unavailable:%s" % (result.stderr.strip() or "ssh failed")
    return result.stdout.strip() or "unavailable:empty"


def read_remote_hash(runner: Runner, node: Node, remote_file: str, timeout_seconds: float) -> str:
    script = "sha256sum %s | awk '{print $1}'" % shlex.quote(remote_file)
    result = run_or_raise(runner, ssh_command(node, script), timeout_seconds)
    value = result.stdout.strip().splitlines()[-1]
    if not value:
        raise RuntimeError("empty sha256 output from %s:%s" % (node.node_id, remote_file))
    return value


def remote_stat_size(runner: Runner, node: Node, remote_file: str, timeout_seconds: float) -> int:
    script = "stat -c %s %s" % (shlex.quote("%s"), shlex.quote(remote_file))
    result = run_or_raise(runner, ssh_command(node, script), timeout_seconds)
    return int(result.stdout.strip().splitlines()[-1])


def plan_lines(nodes: Sequence[Node], remote_repo: str, deploy_root_name: str, run_id: str, target: str, existing_hash: str | None) -> list[str]:
    source = nodes[0]
    build_file = posixpath.join(remote_repo_path(source, remote_repo), target)
    lines = [
        "DEPLOY_DS4_BUILD_PLAN",
        "run_id=%s" % run_id,
        "source_node=%s" % source.node_id,
        "build_repo=%s" % remote_repo_path(source, remote_repo),
        "build_target=%s" % target,
        "build_output=%s" % build_file,
        "existing_build_sha256=%s" % (existing_hash or "not_checked"),
        "deploy_targets:",
    ]
    for node in nodes:
        path = deploy_path(node, deploy_root_name, run_id, target)
        lines.append("  %s:%s" % (node.node_id, path.path))
    lines.append("ring_hops:")
    for left, right in zip(nodes, nodes[1:]):
        left_path = deploy_path(left, deploy_root_name, run_id, target).path
        right_dir = deploy_dir(right, deploy_root_name, run_id)
        lines.append("  %s:%s -> %s:%s" % (left.node_id, left_path, right.node_id, right_dir))
    return lines


def copy_to_deploy_source(runner: Runner, node: Node, remote_repo: str, deploy_root_name: str, run_id: str, target: str, timeout_seconds: float) -> DeployPath:
    src = posixpath.join(remote_repo_path(node, remote_repo), target)
    dst = deploy_path(node, deploy_root_name, run_id, target)
    script = "mkdir -p %s && cp %s %s && chmod 0755 %s" % (
        shlex.quote(posixpath.dirname(dst.path)),
        shlex.quote(src),
        shlex.quote(dst.path),
        shlex.quote(dst.path),
    )
    run_or_raise(runner, ssh_command(node, script), timeout_seconds)
    return dst


def build_source(runner: Runner, node: Node, remote_repo: str, target: str, timeout_seconds: float) -> None:
    script = "cd %s && make %s" % (shlex.quote(remote_repo_path(node, remote_repo)), shlex.quote(target))
    run_or_raise(runner, ssh_command(node, script), timeout_seconds)


def smoke_target(runner: Runner, path: DeployPath, smoke_arg: str, timeout_seconds: float) -> str:
    script = "%s %s 2>&1 | sed -n '1,24p'" % (shlex.quote(path.path), shlex.quote(smoke_arg))
    result = run_or_raise(runner, ssh_command(path.node, script), timeout_seconds)
    return result.stdout


def ring_copy_command(script_dir: Path, left: DeployPath, right: DeployPath, port: int, parallel: int, chunk_mib: int) -> list[str]:
    copy_script = script_dir / "spark_ring_fast_copy.py"
    return [
        sys.executable,
        str(copy_script),
        "--engine",
        "native",
        "--parallel",
        str(parallel),
        "--chunk-mib",
        str(chunk_mib),
        "--port",
        str(port),
        "%s:%s" % (left.node.node_id, left.path),
        "%s:%s/" % (right.node.node_id, posixpath.dirname(right.path)),
    ]


def deploy(args: argparse.Namespace, runner: Runner = default_runner) -> int:
    topology = load_topology(Path(args.topology))
    nodes = validate_nodes(topology, args.nodes)
    validate_ring_hops(topology, [node.node_id for node in nodes])
    existing_hash = None
    source_build = posixpath.join(remote_repo_path(nodes[0], args.remote_repo), args.target)
    if args.dry_run:
        existing_hash = best_effort_existing_hash(runner, nodes[0], source_build, args.timeout_seconds)
    for line in plan_lines(nodes, args.remote_repo, args.deploy_root_name, args.run_id, args.target, existing_hash):
        print(line)
    if args.dry_run:
        print("dry_run=true no remote build, copy, chmod, or smoke commands executed")
        return 0
    start = time.monotonic()
    build_source(runner, nodes[0], args.remote_repo, args.target, args.timeout_seconds)
    source_path = copy_to_deploy_source(runner, nodes[0], args.remote_repo, args.deploy_root_name, args.run_id, args.target, args.timeout_seconds)
    expected_hash = read_remote_hash(runner, nodes[0], source_path.path, args.timeout_seconds)
    expected_size = remote_stat_size(runner, nodes[0], source_path.path, args.timeout_seconds)
    print("source_sha256=%s source_bytes=%d" % (expected_hash, expected_size))
    deployed = [source_path]
    script_dir = Path(__file__).resolve().parent
    for index, (left_node, right_node) in enumerate(zip(nodes, nodes[1:])):
        left_path = deploy_path(left_node, args.deploy_root_name, args.run_id, args.target)
        right_path = deploy_path(right_node, args.deploy_root_name, args.run_id, args.target)
        command = ring_copy_command(script_dir, left_path, right_path, args.port + (index * 100), args.parallel, args.chunk_mib)
        run_or_raise(runner, command, args.timeout_seconds)
        actual_hash = read_remote_hash(runner, right_node, right_path.path, args.timeout_seconds)
        if actual_hash != expected_hash:
            raise RuntimeError("sha mismatch on %s: expected %s got %s" % (right_node.node_id, expected_hash, actual_hash))
        print("verified_sha256 %s:%s %s" % (right_node.node_id, right_path.path, actual_hash))
        deployed.append(right_path)
    for path in deployed:
        output = smoke_target(runner, path, args.smoke_arg, args.timeout_seconds)
        first = output.splitlines()[0] if output.splitlines() else ""
        print("smoke_ok %s:%s first_line=%s" % (path.node.node_id, path.path, first))
    print("DEPLOY_DS4_BUILD_DONE nodes=%d elapsed_seconds=%.3f sha256=%s bytes=%d" % (len(nodes), time.monotonic() - start, expected_hash, expected_size))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build ds4 on one Spark and deploy the binary over Spark ring hops.")
    parser.add_argument("nodes", nargs="+", help="contiguous Spark ring hop list; first node builds, later nodes receive the binary")
    parser.add_argument("--topology", default=DEFAULT_TOPOLOGY)
    parser.add_argument("--remote-repo", default=DEFAULT_REMOTE_REPO)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--deploy-root-name", default=DEFAULT_DEPLOY_ROOT_NAME)
    parser.add_argument("--run-id", default=utc_run_id())
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    parser.add_argument("--chunk-mib", type=int, default=DEFAULT_CHUNK_MIB)
    parser.add_argument("--smoke-arg", default="--help")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return deploy(args)
    except (RuntimeError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
