from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from queue import Queue
import shlex
import sys
from threading import Event, Thread
import time
from types import SimpleNamespace

from .fast_copy import (
    FileItem,
    _copy_file,
    _destination_has_size,
    _discover_rails,
    _list_files,
    _run_ssh,
)
from .service import TransferTopology


DEFAULT_RING_NODES = (
    "spark0",
    "spark1",
    "spark2",
    "spark3",
    "spark4",
    "spark5",
    "spark6",
    "spark7",
    "spark8",
    "spark9",
    "sparka",
    "sparkb",
    "sparkc",
)


@dataclass(frozen=True)
class WaterfallPlan:
    transferable: list[FileItem]
    last_needed_index: dict[str, int]
    edge_files: dict[int, list[FileItem]]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    topology = TransferTopology.load(args.topology)
    nodes = _parse_nodes(args.nodes)
    if args.source_node != nodes[0]:
        raise ValueError("--source-node must be the first node in --nodes for waterfall copy")
    keep_by_node = _load_keep_manifests(nodes, args.manifest_dir, args.keep_manifest_template)
    files = _list_files(topology, args.source_node, args.source_path, args.timeout_s)
    plan = build_waterfall_plan(files, nodes, keep_by_node)
    summary = _plan_summary(args, nodes, files, keep_by_node, plan)
    if args.dry_run:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    _run_waterfall(topology, args, nodes, keep_by_node, plan)
    print(json.dumps({"ok": True, **summary}, indent=2, sort_keys=True))
    return 0


def build_waterfall_plan(files: list[FileItem], nodes: tuple[str, ...], keep_by_node: dict[str, set[str]]) -> WaterfallPlan:
    files_by_relpath = {item.relpath: item for item in files}
    unknown: dict[str, list[str]] = {}
    for node, keep in keep_by_node.items():
        missing = sorted(relpath for relpath in keep if relpath not in files_by_relpath)
        if missing:
            unknown[node] = missing
    if unknown:
        raise ValueError(f"keep manifests reference files missing from source: {unknown}")
    transferable: list[FileItem] = []
    last_needed_index: dict[str, int] = {}
    edge_files: dict[int, list[FileItem]] = {index: [] for index in range(len(nodes) - 1)}
    for item in files:
        indices = [index for index, node in enumerate(nodes) if item.relpath in keep_by_node[node]]
        if not indices:
            continue
        last_index = max(indices)
        last_needed_index[item.relpath] = last_index
        if last_index == 0:
            continue
        transferable.append(item)
        for edge_index in range(last_index):
            edge_files[edge_index].append(item)
    return WaterfallPlan(
        transferable=transferable,
        last_needed_index=last_needed_index,
        edge_files=edge_files,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ds4-waterfall-copy")
    parser.add_argument("--topology", required=True)
    parser.add_argument("--source-node", required=True)
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--destination-path-template", required=True)
    parser.add_argument("--manifest-dir", required=True)
    parser.add_argument("--keep-manifest-template", default="{node}_keep.txt")
    parser.add_argument("--nodes", default=",".join(DEFAULT_RING_NODES))
    parser.add_argument("--port-base", type=int, default=49300)
    parser.add_argument("--port-stride", type=int, default=1000)
    parser.add_argument("--timeout-s", type=int, default=3600)
    parser.add_argument("--striped-file-stripes", type=int, default=8)
    parser.add_argument("--striped-file-threshold-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--remote-v2-dir", default="~/src/ds4_on_spark/v2")
    parser.add_argument("--cleanup-transit", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.port_stride <= args.striped_file_stripes:
        parser.error("--port-stride must be larger than --striped-file-stripes")
    if args.striped_file_stripes < 1:
        parser.error("--striped-file-stripes must be positive")
    if args.striped_file_threshold_bytes < 0:
        parser.error("--striped-file-threshold-bytes must be non-negative")
    return args


def _parse_nodes(raw: str) -> tuple[str, ...]:
    nodes = tuple(node.strip() for node in raw.replace(",", " ").split() if node.strip())
    if len(nodes) < 2:
        raise ValueError("--nodes must name at least two nodes")
    if len(set(nodes)) != len(nodes):
        raise ValueError(f"--nodes contains duplicates: {nodes}")
    return nodes


def _load_keep_manifests(nodes: tuple[str, ...], manifest_dir: str, template: str) -> dict[str, set[str]]:
    root = Path(manifest_dir)
    keep_by_node: dict[str, set[str]] = {}
    for node in nodes:
        path = root / template.format(node=node)
        if not path.exists():
            raise FileNotFoundError(f"missing keep manifest for {node}: {path}")
        keep_by_node[node] = _read_manifest(path)
    return keep_by_node


def _read_manifest(path: Path) -> set[str]:
    keep: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "" or line.startswith("#"):
            continue
        keep.add(line)
    if not keep:
        raise ValueError(f"empty keep manifest: {path}")
    return keep


def _plan_summary(
    args: argparse.Namespace,
    nodes: tuple[str, ...],
    files: list[FileItem],
    keep_by_node: dict[str, set[str]],
    plan: WaterfallPlan,
) -> dict[str, object]:
    edge_summaries = []
    for edge_index, items in plan.edge_files.items():
        edge_summaries.append({
            "edge": f"{nodes[edge_index]}->{nodes[edge_index + 1]}",
            "files": len(items),
            "bytes": sum(item.size for item in items),
            "port_base": args.port_base + (edge_index * args.port_stride),
        })
    return {
        "method": "waterfall_complete_file_relay_v1",
        "source_node": args.source_node,
        "source_path": args.source_path,
        "destination_path_template": args.destination_path_template,
        "nodes": list(nodes),
        "source_files": len(files),
        "source_bytes": sum(item.size for item in files),
        "transfer_files": len(plan.transferable),
        "transfer_bytes": sum(item.size for item in plan.transferable),
        "cleanup_transit": bool(args.cleanup_transit),
        "node_keep_files": {node: len(keep_by_node[node]) for node in nodes},
        "edges": edge_summaries,
    }


def _run_waterfall(
    topology: TransferTopology,
    args: argparse.Namespace,
    nodes: tuple[str, ...],
    keep_by_node: dict[str, set[str]],
    plan: WaterfallPlan,
) -> None:
    queues = [Queue() for _ in range(len(nodes) - 1)]
    stop = Event()
    errors: list[BaseException] = []
    sentinel = object()
    threads = [
        Thread(
            target=_edge_worker,
            args=(topology, args, nodes, keep_by_node, plan, queues, edge_index, sentinel, stop, errors),
            name=f"waterfall-{nodes[edge_index]}-{nodes[edge_index + 1]}",
            daemon=True,
        )
        for edge_index in range(len(queues))
    ]
    for thread in threads:
        thread.start()
    for item in plan.edge_files[0]:
        queues[0].put(item)
    queues[0].put(sentinel)
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]


def _edge_worker(
    topology: TransferTopology,
    args: argparse.Namespace,
    nodes: tuple[str, ...],
    keep_by_node: dict[str, set[str]],
    plan: WaterfallPlan,
    queues: list[Queue],
    edge_index: int,
    sentinel: object,
    stop: Event,
    errors: list[BaseException],
) -> None:
    source_node = nodes[edge_index]
    destination_node = nodes[edge_index + 1]
    source_path = args.source_path if edge_index == 0 else _node_destination_path(args, source_node)
    destination_path = _node_destination_path(args, destination_node)
    copy_args = _copy_args_for_edge(args, edge_index)
    try:
        rails = _discover_rails(topology, source_node, destination_node, args.timeout_s)
        _mkdir(topology, destination_node, destination_path, args.timeout_s)
        while True:
            item = queues[edge_index].get()
            try:
                if item is sentinel:
                    _forward_sentinel(queues, edge_index, sentinel)
                    return
                if stop.is_set():
                    continue
                _copy_or_skip(topology, copy_args, item, rails, source_node, source_path, destination_node, destination_path)
                _cleanup_transit(topology, args, source_node, source_path, item, keep_by_node[source_node], edge_index)
                _forward_file(plan, queues, edge_index, item)
            finally:
                queues[edge_index].task_done()
    except BaseException as exc:
        stop.set()
        errors.append(exc)
        _stop_all_queues(queues, sentinel)


def _copy_or_skip(
    topology: TransferTopology,
    copy_args: SimpleNamespace,
    item: FileItem,
    rails,
    source_node: str,
    source_path: str,
    destination_node: str,
    destination_path: str,
) -> None:
    started = time.time()
    if not _destination_has_size(topology, source_node, source_path, item, copy_args.timeout_s):
        raise RuntimeError(f"source missing or wrong size: {source_node}:{_join(source_path, item.relpath)}")
    if _destination_has_size(topology, destination_node, destination_path, item, copy_args.timeout_s):
        event = "file_present"
    else:
        rail = rails[0]
        _copy_file(topology, copy_args, item, source_node, source_path, destination_node, destination_path, rail, copy_args.port_base)
        event = "file_copied"
    print(json.dumps({
        "event": event,
        "edge": f"{source_node}->{destination_node}",
        "relpath": item.relpath,
        "bytes": item.size,
        "duration_s": round(time.time() - started, 3),
    }, sort_keys=True), flush=True)


def _copy_args_for_edge(args: argparse.Namespace, edge_index: int) -> SimpleNamespace:
    return SimpleNamespace(
        port_base=args.port_base + (edge_index * args.port_stride),
        striped_file_stripes=args.striped_file_stripes,
        striped_file_threshold_bytes=args.striped_file_threshold_bytes,
        remote_v2_dir=args.remote_v2_dir,
        timeout_s=args.timeout_s,
    )


def _cleanup_transit(
    topology: TransferTopology,
    args: argparse.Namespace,
    source_node: str,
    source_path: str,
    item: FileItem,
    source_keep: set[str],
    edge_index: int,
) -> None:
    if not args.cleanup_transit or edge_index == 0:
        return
    if item.relpath in source_keep or not item.relpath.endswith(".safetensors"):
        return
    target = _join(source_path, item.relpath)
    result = _run_ssh(topology, source_node, f"rm -f {shlex.quote(target)}", args.timeout_s)
    if result.returncode != 0:
        raise RuntimeError(f"cleanup failed for {source_node}:{target}: {result.stderr[-1000:]}")
    print(json.dumps({
        "event": "transit_removed",
        "node": source_node,
        "relpath": item.relpath,
    }, sort_keys=True), flush=True)


def _forward_file(plan: WaterfallPlan, queues: list[Queue], edge_index: int, item: FileItem) -> None:
    next_edge = edge_index + 1
    if next_edge >= len(queues):
        return
    if plan.last_needed_index[item.relpath] > next_edge:
        queues[next_edge].put(item)


def _forward_sentinel(queues: list[Queue], edge_index: int, sentinel: object) -> None:
    next_edge = edge_index + 1
    if next_edge < len(queues):
        queues[next_edge].put(sentinel)


def _stop_all_queues(queues: list[Queue], sentinel: object) -> None:
    for queue in queues:
        queue.put(sentinel)


def _mkdir(topology: TransferTopology, node: str, path: str, timeout_s: int) -> None:
    result = _run_ssh(topology, node, f"mkdir -p {shlex.quote(path)}", timeout_s)
    if result.returncode != 0:
        raise RuntimeError(f"mkdir failed for {node}:{path}: {result.stderr[-1000:]}")


def _node_destination_path(args: argparse.Namespace, node: str) -> str:
    return args.destination_path_template.format(node=node)


def _join(root: str, relpath: str) -> str:
    return str(PurePosixPath(root) / relpath)


if __name__ == "__main__":
    sys.exit(main())
