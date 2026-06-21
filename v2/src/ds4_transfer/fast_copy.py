from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import PurePosixPath
import json
import shlex
import subprocess
import sys
import time

from .service import TransferTopology

STAGE_PORT_SPAN = 1000
EDGE_PORT_SPAN = 200


@dataclass(frozen=True)
class FileItem:
    relpath: str
    size: int


@dataclass(frozen=True)
class Rail:
    source_ip: str
    destination_ip: str
    dev: str


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    topology = TransferTopology.load(args.topology)
    files = _list_files(topology, args.source_node, args.source_path, args.include_from, args.timeout_s)
    stages = _selected_stages(topology, args)
    _validate_port_ranges(args, stages)
    plan = {
        "method": "parallel_nc_fanout_200g_v1",
        "source_node": args.source_node,
        "source_path": args.source_path,
        "destination_path": args.destination_path,
        "destination_path_template": args.destination_path_template,
        "files": len(files),
        "bytes": sum(item.size for item in files),
        "stages": stages,
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    for stage_index, edges in enumerate(stages):
        with ThreadPoolExecutor(max_workers=len(edges)) as pool:
            futures = [pool.submit(_copy_edge, topology, args, files, stage_index, edge_index, source, destination) for edge_index, (source, destination) in enumerate(edges)]
            for future in as_completed(futures):
                future.result()
    print(json.dumps({"ok": True, **plan}, indent=2, sort_keys=True))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ds4-fast-copy")
    parser.add_argument("--topology", required=True)
    parser.add_argument("--source-node", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--include-from")
    parser.add_argument("--destination-node")
    parser.add_argument("--destination-path")
    parser.add_argument("--destination-path-template")
    parser.add_argument("--fanout-all", action="store_true")
    parser.add_argument("--jobs-per-edge", type=int, default=16)
    parser.add_argument("--port-base", type=int, default=49300)
    parser.add_argument("--timeout-s", type=int, default=3600)
    parser.add_argument("--striped-file-stripes", type=int, default=8)
    parser.add_argument("--striped-file-threshold-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--remote-v2-dir", default="~/src/ds4_on_spark/v2")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.jobs_per_edge < 1:
        parser.error("--jobs-per-edge must be positive")
    if args.striped_file_stripes < 1:
        parser.error("--striped-file-stripes must be positive")
    if args.striped_file_threshold_bytes < 0:
        parser.error("--striped-file-threshold-bytes must be non-negative")
    if args.fanout_all == (args.destination_node is not None):
        parser.error("use exactly one of --fanout-all or --destination-node")
    if args.destination_node is not None and args.destination_path is None:
        parser.error("--destination-node requires --destination-path")
    if args.fanout_all and args.destination_path_template is None:
        parser.error("--fanout-all requires --destination-path-template")
    return args


def _validate_port_ranges(args: argparse.Namespace, stages: list[list[tuple[str, str]]]) -> None:
    stripe_ports = max(1, args.striped_file_stripes)
    ports_per_edge = args.jobs_per_edge * stripe_ports
    max_edges = max((len(stage) for stage in stages), default=0)
    max_port = args.port_base + ((max(len(stages), 1) - 1) * STAGE_PORT_SPAN) + (max(max_edges - 1, 0) * EDGE_PORT_SPAN) + ports_per_edge - 1
    if ports_per_edge > EDGE_PORT_SPAN:
        raise ValueError(f"jobs_per_edge * striped_file_stripes must fit within {EDGE_PORT_SPAN} ports")
    if max_edges * EDGE_PORT_SPAN > STAGE_PORT_SPAN:
        raise ValueError(f"fanout stage has too many edges for {STAGE_PORT_SPAN} port span")
    if max_port > 65535:
        raise ValueError(f"port range exceeds 65535: {max_port}")


def _selected_stages(topology: TransferTopology, args: argparse.Namespace) -> list[list[tuple[str, str]]]:
    if args.destination_node is not None:
        return [[(args.source_node, args.destination_node)]]
    stages = [[edge for edge in stage] for stage in topology.fanout_stages]
    if not stages:
        raise ValueError("topology has no fanout_stages")
    return stages


def _copy_edge(topology: TransferTopology, args: argparse.Namespace, files: list[FileItem], stage_index: int, edge_index: int, source_node: str, destination_node: str) -> None:
    rails = _discover_rails(topology, source_node, destination_node, args.timeout_s)
    source_path = _path_for_node(args, source_node)
    destination_path = _path_for_node(args, destination_node)
    _run_ssh(topology, destination_node, f"mkdir -p {shlex.quote(destination_path)}", args.timeout_s)
    started = time.time()
    copied = 0
    with ThreadPoolExecutor(max_workers=args.jobs_per_edge) as pool:
        futures = []
        for slot in range(args.jobs_per_edge):
            shard = files[slot::args.jobs_per_edge]
            if shard:
                futures.append(pool.submit(_copy_shard, topology, args, shard, rails, source_node, source_path, destination_node, destination_path, stage_index, edge_index, slot))
        for future in as_completed(futures):
            copied += future.result()
    duration = max(time.time() - started, 0.001)
    print(json.dumps({"edge": f"{source_node}->{destination_node}", "files": copied, "duration_s": round(duration, 3), "gbit_s": round((sum(item.size for item in files) * 8) / duration / 1_000_000_000, 3)}, sort_keys=True), flush=True)


def _copy_shard(topology: TransferTopology, args: argparse.Namespace, files: list[FileItem], rails: list[Rail], source_node: str, source_path: str, destination_node: str, destination_path: str, stage_index: int, edge_index: int, slot: int) -> int:
    copied = 0
    port = _port_for_shard(args, stage_index, edge_index, slot)
    for index, item in enumerate(files):
        rail = rails[(slot + index) % len(rails)]
        if _destination_has_size(topology, destination_node, destination_path, item, args.timeout_s):
            continue
        _copy_file(topology, args, item, source_node, source_path, destination_node, destination_path, rail, port)
        copied += 1
    return copied


def _port_for_shard(args: argparse.Namespace, stage_index: int, edge_index: int, slot: int) -> int:
    stripe_ports = max(1, args.striped_file_stripes)
    return args.port_base + (stage_index * STAGE_PORT_SPAN) + (edge_index * EDGE_PORT_SPAN) + (slot * stripe_ports)


def _copy_file(topology: TransferTopology, args: argparse.Namespace, item: FileItem, source_node: str, source_path: str, destination_node: str, destination_path: str, rail: Rail, port: int) -> None:
    src = _join(source_path, item.relpath)
    dst = _join(destination_path, item.relpath)
    if item.size >= args.striped_file_threshold_bytes and args.striped_file_stripes > 1:
        _copy_file_striped(topology, args, item, source_node, src, destination_node, dst, rail, port)
        return
    tmp = f"{dst}.ds4tmp"
    parent = str(PurePosixPath(dst).parent)
    server_script = "set -eu; mkdir -p {parent}; rm -f {tmp}; nc -l -s {bind} -p {port} > {tmp}; mv {tmp} {dst}".format(
        parent=shlex.quote(parent),
        tmp=shlex.quote(tmp),
        bind=shlex.quote(rail.destination_ip),
        port=port,
        dst=shlex.quote(dst),
    )
    client_script = "set -eu; for i in $(seq 1 50); do nc -N -s {bind} {dst_ip} {port} < {src} && exit 0; sleep 0.2; done; exit 1".format(
        bind=shlex.quote(rail.source_ip),
        dst_ip=shlex.quote(rail.destination_ip),
        port=port,
        src=shlex.quote(src),
    )
    server = _popen_ssh(topology, destination_node, server_script)
    time.sleep(0.2)
    try:
        client = _run_ssh(topology, source_node, client_script, args.timeout_s)
        if client.returncode != 0:
            if server.poll() is None:
                server.kill()
            raise RuntimeError(f"copy client failed for {item.relpath}: {client.stderr[-1000:]}")
        rc = server.wait(timeout=args.timeout_s)
    finally:
        if server.poll() is None:
            server.kill()
    if rc != 0:
        stderr = server.stderr.read()[-1000:] if server.stderr is not None else ""
        raise RuntimeError(f"copy server failed for {item.relpath}: {stderr}")
    if not _destination_has_size(topology, destination_node, destination_path, item, args.timeout_s):
        raise RuntimeError(f"destination size mismatch for {destination_node}:{dst}")


def _copy_file_striped(topology: TransferTopology, args: argparse.Namespace, item: FileItem, source_node: str, src: str, destination_node: str, dst: str, rail: Rail, port: int) -> None:
    server_script = _striped_server_script(args, item, dst, rail, port)
    client_script = _striped_client_script(args, src, rail, port)
    _run_striped_copy(topology, args, item, source_node, destination_node, server_script, client_script)
    _verify_striped_destination(topology, args, item, destination_node, dst)


def _striped_remote_python(args: argparse.Namespace) -> str:
    return "cd {v2}; PYTHONPATH=src python3 -m ds4_transfer.striped_channel".format(v2=_quote_remote_path(args.remote_v2_dir))


def _quote_remote_path(path: str) -> str:
    if path == "~":
        return "~"
    if path.startswith("~/"):
        return "~/" + "/".join(shlex.quote(part) for part in path[2:].split("/"))
    return shlex.quote(path)


def _striped_server_script(
    args: argparse.Namespace,
    item: FileItem,
    dst: str,
    rail: Rail,
    port: int,
) -> str:
    tmp = f"{dst}.ds4tmp"
    parent = str(PurePosixPath(dst).parent)
    return (
        "set -eu; mkdir -p {parent}; rm -f {tmp}; "
        "{python} recv-file --bind-ip {bind} --port-base {port} --stripes {stripes} "
        "--size {size} --output {tmp} --timeout-s {timeout}; "
        "mv {tmp} {dst}"
    ).format(
        parent=shlex.quote(parent),
        tmp=shlex.quote(tmp),
        python=_striped_remote_python(args),
        bind=shlex.quote(rail.destination_ip),
        port=port,
        stripes=args.striped_file_stripes,
        size=item.size,
        timeout=args.timeout_s,
        dst=shlex.quote(dst),
    )


def _striped_client_script(
    args: argparse.Namespace,
    src: str,
    rail: Rail,
    port: int,
) -> str:
    return (
        "set -eu; {python} send-file --source {src} --source-ip {source_ip} "
        "--destination-ip {destination_ip} --port-base {port} --stripes {stripes} "
        "--timeout-s {timeout}"
    ).format(
        python=_striped_remote_python(args),
        src=shlex.quote(src),
        source_ip=shlex.quote(rail.source_ip),
        destination_ip=shlex.quote(rail.destination_ip),
        port=port,
        stripes=args.striped_file_stripes,
        timeout=args.timeout_s,
    )


def _run_striped_copy(
    topology: TransferTopology,
    args: argparse.Namespace,
    item: FileItem,
    source_node: str,
    destination_node: str,
    server_script: str,
    client_script: str,
) -> None:
    server = _popen_ssh(topology, destination_node, server_script)
    time.sleep(0.3)
    client = _popen_ssh(topology, source_node, client_script)
    deadline = time.monotonic() + args.timeout_s
    try:
        while client.poll() is None:
            if server.poll() is not None:
                if server.returncode != 0:
                    _, server_stderr = server.communicate()
                    client.kill()
                    _, client_stderr = client.communicate()
                    raise RuntimeError(f"striped copy server failed for {item.relpath}: {server_stderr[-1000:] or client_stderr[-1000:]}")
            if time.monotonic() > deadline:
                client.kill()
                server.kill()
                raise TimeoutError(f"striped copy timed out for {item.relpath}")
            time.sleep(0.1)
        _, client_stderr = client.communicate()
        if client.returncode != 0:
            if server.poll() is None:
                server.kill()
            raise RuntimeError(f"striped copy client failed for {item.relpath}: {client_stderr[-1000:]}")
        rc = server.wait(timeout=max(1.0, deadline - time.monotonic()))
    finally:
        if client.poll() is None:
            client.kill()
        if server.poll() is None:
            server.kill()
    if rc != 0:
        stderr = server.stderr.read()[-1000:] if server.stderr is not None else ""
        raise RuntimeError(f"striped copy server failed for {item.relpath}: {stderr}")


def _verify_striped_destination(
    topology: TransferTopology,
    args: argparse.Namespace,
    item: FileItem,
    destination_node: str,
    dst: str,
) -> None:
    result = _run_ssh(topology, destination_node, f"test $(stat -c %s {shlex.quote(dst)}) -eq {item.size}", args.timeout_s)
    if result.returncode != 0:
        raise RuntimeError(f"destination size mismatch for {destination_node}:{dst}")


def _list_files(topology: TransferTopology, source_node: str, source_path: str, include_from: str | None, timeout_s: int) -> list[FileItem]:
    if include_from is not None:
        return _list_included_files(topology, source_node, source_path, include_from, timeout_s)
    return _list_all_files(topology, source_node, source_path, timeout_s)


def _list_all_files(topology: TransferTopology, source_node: str, source_path: str, timeout_s: int) -> list[FileItem]:
    script = "cd {path}; find . -type f ! -path './.cache/*' -printf '%P\\t%s\\n' | sort".format(path=shlex.quote(source_path))
    result = _run_ssh(topology, source_node, script, timeout_s)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    files: list[FileItem] = []
    for line in result.stdout.splitlines():
        if line.strip() == "":
            continue
        relpath, size = line.rsplit("\t", 1)
        files.append(FileItem(relpath=relpath, size=int(size)))
    if not files:
        raise ValueError(f"no files found under {source_node}:{source_path}")
    return files


def _read_include_manifest(path: str) -> list[str]:
    relpaths: list[str] = []
    seen: set[str] = set()
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line == "" or line.startswith("#"):
                continue
            relpath = line.removeprefix("./")
            if relpath.startswith("../") or relpath.startswith("/"):
                raise ValueError(f"include path must be relative: {line}")
            if relpath not in seen:
                relpaths.append(relpath)
                seen.add(relpath)
    if not relpaths:
        raise ValueError(f"include manifest is empty: {path}")
    return sorted(relpaths)


def _list_included_files(topology: TransferTopology, source_node: str, source_path: str, include_from: str, timeout_s: int) -> list[FileItem]:
    relpaths = _read_include_manifest(include_from)
    body = "; ".join(
        "test -f {rel} && printf '%s\\t%s\\n' {rel} $(stat -c %s {rel})".format(rel=shlex.quote(relpath))
        for relpath in relpaths
    )
    script = "set -eu; cd {path}; {body}".format(path=shlex.quote(source_path), body=body)
    result = _run_ssh(topology, source_node, script, timeout_s)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    files: list[FileItem] = []
    for line in result.stdout.splitlines():
        if line.strip() == "":
            continue
        relpath, size = line.rsplit("\t", 1)
        files.append(FileItem(relpath=relpath, size=int(size)))
    found = {item.relpath for item in files}
    missing = [relpath for relpath in relpaths if relpath not in found]
    if missing:
        raise ValueError(f"include manifest has missing source files: {missing[:10]}")
    return files


def _discover_rails(topology: TransferTopology, source_node: str, destination_node: str, timeout_s: int) -> list[Rail]:
    destination = topology.get_node(destination_node)
    target = destination.fabric_ip or destination.fabric_host
    route = _run_ssh(topology, source_node, f"ip route show {shlex.quote(target)}", timeout_s)
    if route.returncode != 0:
        raise RuntimeError(route.stderr)
    rails: list[Rail] = []
    tokens = route.stdout.replace("\n", " ").split()
    for index, token in enumerate(tokens):
        if token == "via" and index + 3 < len(tokens) and tokens[index + 2] == "dev":
            candidate_ip = tokens[index + 1]
            dev = tokens[index + 3]
            if _node_has_ip(topology, destination_node, candidate_ip, timeout_s):
                dst_ip = candidate_ip
                src_ip = _source_ip_for_dev(topology, source_node, dev, timeout_s)
            else:
                dst_ip = target
                src_ip = topology.get_node(source_node).fabric_ip or topology.get_node(source_node).fabric_host
            rails.append(Rail(source_ip=src_ip, destination_ip=dst_ip, dev=dev))
    if rails:
        return rails
    fallback = _run_ssh(topology, source_node, f"ip route get {shlex.quote(target)}", timeout_s)
    if fallback.returncode != 0:
        raise RuntimeError(fallback.stderr)
    words = fallback.stdout.split()
    if "via" not in words or "dev" not in words:
        raise RuntimeError(f"could not discover 200G rail from {source_node} to {destination_node}: {fallback.stdout}")
    candidate_ip = words[words.index("via") + 1]
    dev = words[words.index("dev") + 1]
    if _node_has_ip(topology, destination_node, candidate_ip, timeout_s):
        return [Rail(source_ip=_source_ip_for_dev(topology, source_node, dev, timeout_s), destination_ip=candidate_ip, dev=dev)]
    return [Rail(source_ip=topology.get_node(source_node).fabric_ip or topology.get_node(source_node).fabric_host, destination_ip=target, dev=dev)]


def _node_has_ip(topology: TransferTopology, node: str, ip: str, timeout_s: int) -> bool:
    script = "ip -4 -o addr show scope global | awk -v ip={ip} '{{split($4,a,\"/\"); if (a[1] == ip) found=1}} END {{exit(found ? 0 : 1)}}'".format(ip=shlex.quote(ip))
    result = _run_ssh(topology, node, script, timeout_s)
    return result.returncode == 0


def _source_ip_for_dev(topology: TransferTopology, node: str, dev: str, timeout_s: int) -> str:
    script = "ip -4 -o addr show dev {dev} scope global | awk '{{split($4,a,\"/\"); print a[1]; exit}}'".format(dev=shlex.quote(dev))
    result = _run_ssh(topology, node, script, timeout_s)
    if result.returncode != 0 or result.stdout.strip() == "":
        raise RuntimeError(f"no source ip for {node}:{dev}: {result.stderr}")
    return result.stdout.strip()


def _destination_has_size(topology: TransferTopology, node: str, destination_path: str, item: FileItem, timeout_s: int) -> bool:
    dst = _join(destination_path, item.relpath)
    result = _run_ssh(topology, node, f"stat -c %s {shlex.quote(dst)} 2>/dev/null || true", timeout_s)
    return result.returncode == 0 and result.stdout.strip() == str(item.size)


def _path_for_node(args: argparse.Namespace, node: str) -> str:
    if args.destination_path_template is not None:
        return args.destination_path_template.format(node=node)
    if node == args.source_node:
        return args.source_path
    return args.destination_path


def _join(root: str, relpath: str) -> str:
    return str(PurePosixPath(root) / relpath)


def _run_ssh(topology: TransferTopology, node: str, script: str, timeout_s: int) -> subprocess.CompletedProcess[str]:
    host = topology.get_node(node).host
    return subprocess.run(["ssh", *topology.ssh_options, host, script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_s, check=False)


def _popen_ssh(topology: TransferTopology, node: str, script: str) -> subprocess.Popen[str]:
    host = topology.get_node(node).host
    return subprocess.Popen(["ssh", *topology.ssh_options, host, script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


if __name__ == "__main__":
    sys.exit(main())
