#!/usr/bin/env python3
"""Waterfall-distribute a sharded HF model into per-rank stage directories.

The source full model tree lives on rank 0, normally spark0 external NVMe.
Each rank keeps only files needed by its pipeline stage in the normal local
model directory. Files are forwarded one adjacent node at a time; as soon as a
rank receives a complete file, it can install it locally and forward it onward.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LAYER_REGEX = r"model\.layers\.(\d+)\."
DEFAULT_STAGE_TEMPLATE = "/home/{node}/models/hf/{repo_id}"
DEFAULT_HANDOFF_TEMPLATE = "/home/{node}/ds4_waterfall/{run_id}"
DEFAULT_REMOTE_SCRIPT = "/tmp/ds4_waterfall_stage_model.py"
DEFAULT_REMOTE_MANIFEST = "/tmp/ds4_waterfall_manifest_{run_id}.json"
DEFAULT_REMOTE_V2_DIR = "~/src/ds4_on_spark/v2"
DEFAULT_TRANSFER_TOPOLOGY = "profiles/transfer/spark_200g.json"
DEFAULT_SSH_OPTIONS = [
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
]


@dataclass(frozen=True)
class FilePlan:
    rel: str
    size: int
    needed_ranks: tuple[int, ...]
    is_safetensors: bool


def run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def run_passthrough(argv: list[str]) -> None:
    proc = subprocess.run(argv)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def ssh_argv(host: str, command: str) -> list[str]:
    return ["ssh", *DEFAULT_SSH_OPTIONS, host, command]


def scp_argv(src: str, dst: str) -> list[str]:
    return ["scp", "-q", *DEFAULT_SSH_OPTIONS, src, dst]


def rsync_ssh() -> str:
    return " ".join(shlex.quote(item) for item in ["ssh", *DEFAULT_SSH_OPTIONS])


def shell_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(item) for item in argv)


def quote_shell_path(path: str) -> str:
    if path == "~":
        return "~"
    if path.startswith("~/"):
        return "~/" + "/".join(shlex.quote(part) for part in path[2:].split("/"))
    return shlex.quote(path)


def parse_csv(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def parse_partition(text: str | list[int]) -> list[int]:
    if isinstance(text, list):
        out = [int(item) for item in text]
    else:
        out = [int(item) for item in parse_csv(text)]
    if not out or any(item <= 0 for item in out):
        raise SystemExit("partition must be a comma-separated list of positive integers")
    return out


def bounds_for(partition: list[int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    cursor = 0
    for count in partition:
        out.append((cursor, cursor + count))
        cursor += count
    return out


def rank_for_layer(bounds: list[tuple[int, int]], layer: int) -> int:
    for rank, (start, end) in enumerate(bounds):
        if start <= layer < end:
            return rank
    raise SystemExit(f"layer {layer} is outside partition bounds")


def load_weight_map(source_dir: Path) -> dict[str, str]:
    index_path = source_dir / "model.safetensors.index.json"
    if not index_path.exists():
        raise SystemExit(f"missing index: {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    weight_map = data.get("weight_map")
    if not isinstance(weight_map, dict):
        raise SystemExit("model.safetensors.index.json does not contain a weight_map object")
    return {str(tensor): str(shard) for tensor, shard in weight_map.items()}


def shard_rank_sets(source_dir: Path, partition: list[int], layer_regex: str) -> dict[str, set[int]]:
    bounds = bounds_for(partition)
    total_layers = sum(partition)
    rex = re.compile(layer_regex)
    ranks_by_shard: dict[str, set[int]] = {}
    for tensor, shard in load_weight_map(source_dir).items():
        match = rex.search(tensor)
        ranks = ranks_by_shard.setdefault(shard, set())
        if match is None:
            ranks.update(range(len(partition)))
            continue
        layer = int(match.group(1))
        if layer >= total_layers:
            ranks.update(range(len(partition)))
            continue
        ranks.add(rank_for_layer(bounds, layer))
    return ranks_by_shard


def iter_files(source_dir: Path, *, skip_cache: bool) -> list[Path]:
    files: list[Path] = []
    for root, dirs, names in os.walk(source_dir):
        if skip_cache and ".cache" in dirs:
            dirs.remove(".cache")
        root_path = Path(root)
        for name in names:
            path = root_path / name
            if path.is_file():
                files.append(path.relative_to(source_dir))
    return sorted(files)


def partial_downloads(source_dir: Path, *, skip_cache: bool) -> list[str]:
    return [path.as_posix() for path in iter_files(source_dir, skip_cache=skip_cache) if path.name.endswith(".part")]


def build_plan(args: argparse.Namespace) -> list[FilePlan]:
    source_dir = Path(args.source_full_dir)
    partition = parse_partition(args.partition)
    if len(partition) != len(args.nodes):
        raise SystemExit("partition width must match --nodes count")
    ranks_by_shard = shard_rank_sets(source_dir, partition, args.layer_regex)
    allow_partial = bool(getattr(args, "allow_partial", False))
    watch_source = bool(getattr(args, "watch_source", False))
    partials = partial_downloads(source_dir, skip_cache=args.skip_cache)
    if partials and not allow_partial and not watch_source:
        raise SystemExit("partial download files present: " + ",".join(partials[:8]))
    missing_shards = sorted(shard for shard in ranks_by_shard if not (source_dir / shard).is_file())
    if missing_shards and not allow_partial and not watch_source:
        raise SystemExit("missing indexed shards: " + ",".join(missing_shards[:8]))
    file_plans: list[FilePlan] = []
    planned: set[str] = set()
    for rel_path in iter_files(source_dir, skip_cache=args.skip_cache):
        rel = rel_path.as_posix()
        if rel_path.name.endswith(".part"):
            continue
        path = source_dir / rel_path
        is_safetensors = path.suffix == ".safetensors"
        ranks: set[int]
        if is_safetensors:
            ranks = set(ranks_by_shard.get(rel, set()))
            if not ranks and args.extra_safetensors == "all":
                ranks = set(range(len(partition)))
            elif not ranks and args.extra_safetensors == "rank0":
                ranks = {0}
        else:
            ranks = set(range(len(partition)))
        if ranks:
            file_plans.append(FilePlan(rel=rel, size=path.stat().st_size, needed_ranks=tuple(sorted(ranks)), is_safetensors=is_safetensors))
            planned.add(rel)
    if watch_source:
        for rel, ranks in sorted(ranks_by_shard.items()):
            if rel not in planned and ranks:
                file_plans.append(FilePlan(rel=rel, size=-1, needed_ranks=tuple(sorted(ranks)), is_safetensors=True))
    return file_plans


def template(text: str, *, node: str, rank: int, run_id: str, repo_id: str) -> str:
    return text.format(node=node, rank=rank, run_id=run_id, repo_id=repo_id)


def host_for(node: str, template_text: str) -> str:
    return template_text.format(node=node)


def same_size(path: Path, size: int) -> bool:
    if not path.exists() or not path.is_file():
        return False
    return size < 0 or path.stat().st_size == size


def install_local(src: Path, dst: Path, size: int, *, link_mode: str) -> None:
    if same_size(dst, size):
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    if tmp.exists():
        tmp.unlink()
    if link_mode in {"auto", "hardlink"}:
        try:
            os.link(src, tmp)
        except OSError:
            if link_mode == "hardlink":
                raise
            shutil.copy2(src, tmp)
    else:
        shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def remote_final_exists(host: str, dst: str, size: int) -> bool:
    if size < 0:
        cmd = f"test -f {shlex.quote(dst)}"
    else:
        cmd = f"test -f {shlex.quote(dst)} && test $(stat -c%s {shlex.quote(dst)}) -eq {int(size)}"
    return run(ssh_argv(host, cmd), check=False).returncode == 0


def write_include_manifest(rel: str) -> Path:
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"ds4_waterfall_include_{os.getpid()}_{digest}.txt"
    path.write_text(rel + "\n", encoding="utf-8")
    return path


def fast_copy_file(
    *,
    rel: str,
    source_node: str,
    source_base: str,
    dest_node: str,
    dest_base: str,
    manifest: dict[str, Any],
) -> None:
    include_path = write_include_manifest(rel)
    try:
        argv = [
            "python3",
            "-m",
            "ds4_transfer.fast_copy",
            "--topology",
            str(manifest["transfer_topology"]),
            "--source-node",
            source_node,
            "--source-path",
            source_base,
            "--include-from",
            str(include_path),
            "--destination-node",
            dest_node,
            "--destination-path",
            dest_base,
            "--jobs-per-edge",
            str(manifest["fast_copy_jobs_per_edge"]),
            "--port-base",
            str(manifest["fast_copy_port_base"]),
            "--striped-file-stripes",
            str(manifest["striped_file_stripes"]),
            "--striped-file-threshold-bytes",
            str(manifest["striped_file_threshold_bytes"]),
            "--timeout-s",
            str(manifest["fast_copy_timeout_s"]),
            "--remote-v2-dir",
            str(manifest["remote_v2_dir"]),
        ]
        cmd = f"cd {quote_shell_path(str(manifest['remote_v2_dir']))}; PYTHONPATH=src {shell_join(argv)}"
        run_passthrough(["bash", "-lc", cmd])
    finally:
        try:
            include_path.unlink()
        except FileNotFoundError:
            pass


def rsync_file(src: Path, *, rel: str, host: str, dest_base: str, rsync_bwlimit: str | None) -> None:
    dest = f"{dest_base.rstrip('/')}/{rel}"
    dest_parent = str(Path(dest).parent)
    tmp = dest + ".part"
    run(ssh_argv(host, f"mkdir -p {shlex.quote(dest_parent)}"))
    rsync = ["rsync", "-a", "--partial", "-e", rsync_ssh()]
    if rsync_bwlimit:
        rsync.append(f"--bwlimit={rsync_bwlimit}")
    rsync.extend([str(src), f"{host}:{tmp}"])
    run_passthrough(rsync)
    run(ssh_argv(host, f"mv -f {shlex.quote(tmp)} {shlex.quote(dest)}"))


def send_file(
    src: Path,
    *,
    rel: str,
    size: int,
    source_node: str,
    source_base: str,
    dest_node: str,
    host: str,
    dest_base: str,
    manifest: dict[str, Any],
) -> None:
    dest = f"{dest_base.rstrip('/')}/{rel}"
    if remote_final_exists(host, dest, size):
        return
    if manifest.get("transfer_mode") == "rsync":
        rsync_file(src, rel=rel, host=host, dest_base=dest_base, rsync_bwlimit=manifest.get("rsync_bwlimit"))
        return
    fast_copy_file(rel=rel, source_node=source_node, source_base=source_base, dest_node=dest_node, dest_base=dest_base, manifest=manifest)


def prepare_local_stage(stage_dir: Path, *, replace_existing: bool, run_id: str) -> None:
    if not stage_dir.exists():
        stage_dir.mkdir(parents=True)
        return
    if not replace_existing:
        raise SystemExit(f"stage dir exists; pass --replace-existing to move it aside: {stage_dir}")
    backup = stage_dir.with_name(stage_dir.name + f".waterfall-backup-{run_id}")
    if backup.exists():
        raise SystemExit(f"backup already exists: {backup}")
    stage_dir.rename(backup)
    stage_dir.mkdir(parents=True)


def remote_prepare(host: str, stage_dir: str, handoff_dir: str, *, replace_existing: bool, run_id: str) -> None:
    script = """
set -euo pipefail
stage=$1
handoff=$2
replace=$3
run_id=$4
mkdir -p "$handoff"
if [ -e "$stage" ]; then
    if [ "$replace" != 1 ]; then
        echo "stage dir exists: $stage" >&2
        exit 17
    fi
    backup="${stage}.waterfall-backup-${run_id}"
    if [ -e "$backup" ]; then
        echo "backup exists: $backup" >&2
        exit 18
    fi
    mv "$stage" "$backup"
fi
mkdir -p "$stage"
"""
    cmd = "bash -s -- " + " ".join(shlex.quote(item) for item in [stage_dir, handoff_dir, "1" if replace_existing else "0", run_id])
    proc = subprocess.run(ssh_argv(host, cmd), input=script, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)


def write_marker(stage_dir: Path, manifest: dict[str, Any], rank: int, files: list[FilePlan]) -> None:
    rank_files = [item.rel for item in files if rank in item.needed_ranks]
    marker = {
        "format": "ds4-waterfall-stage-model-v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run_id": manifest["run_id"],
        "source_full_dir": manifest["source_full_dir"],
        "rank": rank,
        "node": manifest["nodes"][rank],
        "partition": manifest["partition"],
        "required_files": rank_files,
    }
    (stage_dir / ".ds4_stage_view.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def wait_for_file(path: Path, size: int, *, timeout_s: int, poll_s: float) -> None:
    start = time.monotonic()
    while not same_size(path, size):
        if timeout_s > 0 and time.monotonic() - start > timeout_s:
            raise SystemExit(f"timed out waiting for {path}")
        time.sleep(poll_s)


def ready_file(path: Path, size: int) -> bool:
    return same_size(path, size) and not path.name.endswith(".part")


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_plans_from_manifest(manifest: dict[str, Any]) -> list[FilePlan]:
    return [
        FilePlan(
            rel=str(item["rel"]),
            size=int(item["size"]),
            needed_ranks=tuple(int(rank) for rank in item["needed_ranks"]),
            is_safetensors=bool(item["is_safetensors"]),
        )
        for item in manifest["files"]
    ]


def process_worker_file(
    item: FilePlan,
    *,
    rank: int,
    src: Path,
    stage_dir: Path,
    handoff_dir: Path,
    next_node: str,
    next_host: str,
    next_handoff: str,
    manifest: dict[str, Any],
) -> None:
    nodes = list(manifest["nodes"])
    max_rank = max(item.needed_ranks)
    if rank < max_rank:
        send_file(
            src,
            rel=item.rel,
            size=item.size,
            source_node=nodes[rank],
            source_base=str(handoff_dir),
            dest_node=next_node,
            host=next_host,
            dest_base=next_handoff,
            manifest=manifest,
        )
    if rank in item.needed_ranks:
        install_local(src, stage_dir / item.rel, item.size, link_mode=str(manifest["link_mode"]))
    if manifest["cleanup_handoff"]:
        try:
            src.unlink()
        except FileNotFoundError:
            pass


def worker_stream_main(manifest: dict[str, Any], files: list[FilePlan], rank: int, stage_dir: Path, handoff_dir: Path, next_host: str, next_handoff: str) -> None:
    pending = [item for item in files if rank <= max(item.needed_ranks)]
    start = time.monotonic()
    while pending:
        progressed = False
        for item in list(pending):
            src = handoff_dir / item.rel
            if not ready_file(src, item.size):
                continue
            process_worker_file(item, rank=rank, src=src, stage_dir=stage_dir, handoff_dir=handoff_dir, next_node=str(manifest["nodes"][rank + 1]) if rank + 1 < len(manifest["nodes"]) else "", next_host=next_host, next_handoff=next_handoff, manifest=manifest)
            pending.remove(item)
            progressed = True
        if progressed:
            continue
        timeout_s = int(manifest["wait_timeout_s"])
        if timeout_s > 0 and time.monotonic() - start > timeout_s:
            raise SystemExit(f"timed out waiting for {len(pending)} files in {handoff_dir}")
        time.sleep(float(manifest["poll_s"]))


def worker_main(args: argparse.Namespace) -> int:
    manifest = load_manifest(Path(args.manifest))
    files = file_plans_from_manifest(manifest)
    rank = args.worker_rank
    nodes = list(manifest["nodes"])
    node = nodes[rank]
    run_id = str(manifest["run_id"])
    repo_id = str(manifest["repo_id"])
    stage_dir = Path(template(manifest["stage_dir_template"], node=node, rank=rank, run_id=run_id, repo_id=repo_id))
    handoff_dir = Path(template(manifest["handoff_dir_template"], node=node, rank=rank, run_id=run_id, repo_id=repo_id))
    next_host = ""
    next_handoff = ""
    if rank + 1 < len(nodes):
        next_node = nodes[rank + 1]
        next_host = host_for(next_node, str(manifest["ssh_host_template"]))
        next_handoff = template(manifest["handoff_dir_template"], node=next_node, rank=rank + 1, run_id=run_id, repo_id=repo_id)
    if manifest.get("watch_source"):
        worker_stream_main(manifest, files, rank, stage_dir, handoff_dir, next_host, next_handoff)
        write_marker(stage_dir, manifest, rank, files)
        return 0
    for item in files:
        max_rank = max(item.needed_ranks)
        if rank > max_rank:
            continue
        src = handoff_dir / item.rel
        wait_for_file(src, item.size, timeout_s=int(manifest["wait_timeout_s"]), poll_s=float(manifest["poll_s"]))
        process_worker_file(item, rank=rank, src=src, stage_dir=stage_dir, handoff_dir=handoff_dir, next_node=next_node if rank + 1 < len(nodes) else "", next_host=next_host, next_handoff=next_handoff, manifest=manifest)
    write_marker(stage_dir, manifest, rank, files)
    return 0


def summarize(files: list[FilePlan], node_count: int) -> dict[str, Any]:
    by_rank = []
    by_edge = []
    for rank in range(node_count):
        selected = [item for item in files if rank in item.needed_ranks]
        by_rank.append({"rank": rank, "files": len(selected), "bytes": sum(max(0, item.size) for item in selected)})
    for edge in range(node_count - 1):
        crossing = [item for item in files if max(item.needed_ranks) > edge]
        by_edge.append({"edge": [edge, edge + 1], "files": len(crossing), "bytes": sum(max(0, item.size) for item in crossing)})
    return {"rank_stage_totals": by_rank, "edge_transfer_totals": by_edge}


def start_worker(host: str, rank: int, remote_script: str, remote_manifest: str, log_path: str) -> int:
    cmd = (
        f"mkdir -p {shlex.quote(str(Path(log_path).parent))}; "
        f"nohup python3 {shlex.quote(remote_script)} --worker --manifest {shlex.quote(remote_manifest)} "
        f"--worker-rank {rank} < /dev/null > {shlex.quote(log_path)} 2>&1 & echo $!"
    )
    proc = run(ssh_argv(host, cmd))
    return int(proc.stdout.strip().splitlines()[-1])


def wait_worker(host: str, pid: int, log_path: str) -> None:
    while True:
        proc = run(ssh_argv(host, f"kill -0 {pid} >/dev/null 2>&1"), check=False)
        if proc.returncode != 0:
            break
        time.sleep(10)
    proc = run(ssh_argv(host, f"tail -n 20 {shlex.quote(log_path)}"), check=False)
    if proc.stdout:
        print(proc.stdout, end="")


def orchestrator_stream_files(files: list[FilePlan], *, source_dir: Path, stage0: Path, first_node: str, first_host: str, first_handoff: str, manifest: dict[str, Any], args: argparse.Namespace) -> None:
    pending = list(files)
    start = time.monotonic()
    while pending:
        progressed = False
        for item in list(pending):
            src = source_dir / item.rel
            if not ready_file(src, item.size):
                continue
            if max(item.needed_ranks) > 0:
                send_file(src, rel=item.rel, size=item.size, source_node=args.nodes[0], source_base=str(source_dir), dest_node=first_node, host=first_host, dest_base=first_handoff, manifest=manifest)
            if 0 in item.needed_ranks:
                install_local(src, stage0 / item.rel, item.size, link_mode=args.link_mode)
            pending.remove(item)
            progressed = True
            print(json.dumps({"status": "streamed", "rel": item.rel, "remaining": len(pending)}), flush=True)
        if progressed:
            continue
        if args.wait_timeout_s > 0 and time.monotonic() - start > args.wait_timeout_s:
            raise SystemExit(f"timed out waiting for {len(pending)} source files in {source_dir}")
        time.sleep(args.poll_s)


def orchestrator_main(args: argparse.Namespace) -> int:
    args.nodes = parse_csv(args.nodes)
    args.partition = parse_partition(args.partition)
    if len(args.nodes) != len(args.partition):
        raise SystemExit("--nodes count must match --partition width")
    source_dir = Path(args.source_full_dir)
    if not source_dir.is_dir():
        raise SystemExit(f"missing source full model dir: {source_dir}")
    run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    files = build_plan(args)
    manifest = {
        "format": "ds4-waterfall-stage-model-manifest-v1",
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repo_id": args.repo_id,
        "source_full_dir": str(source_dir),
        "nodes": args.nodes,
        "partition": args.partition,
        "stage_dir_template": args.stage_dir_template,
        "handoff_dir_template": args.handoff_dir_template,
        "ssh_host_template": args.ssh_host_template,
        "link_mode": args.link_mode,
        "cleanup_handoff": args.cleanup_handoff,
        "wait_timeout_s": args.wait_timeout_s,
        "poll_s": args.poll_s,
        "rsync_bwlimit": args.rsync_bwlimit,
        "transfer_mode": args.transfer_mode,
        "remote_v2_dir": args.remote_v2_dir,
        "transfer_topology": args.transfer_topology,
        "fast_copy_jobs_per_edge": args.fast_copy_jobs_per_edge,
        "fast_copy_port_base": args.fast_copy_port_base,
        "fast_copy_timeout_s": args.fast_copy_timeout_s,
        "striped_file_stripes": args.striped_file_stripes,
        "striped_file_threshold_bytes": args.striped_file_threshold_bytes,
        "watch_source": args.watch_source,
        "files": [item.__dict__ for item in files],
        "summary": summarize(files, len(args.nodes)),
    }
    print(json.dumps({"status": "planned", "run_id": run_id, "files": len(files), **manifest["summary"]}, indent=2, sort_keys=True))
    if not args.execute:
        return 0
    remote_manifest = DEFAULT_REMOTE_MANIFEST.format(run_id=run_id)
    local_manifest = Path(f"/tmp/ds4_waterfall_manifest_{run_id}.json")
    local_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    remote_script = args.remote_script
    this_script = Path(__file__).resolve()
    stage0 = Path(template(args.stage_dir_template, node=args.nodes[0], rank=0, run_id=run_id, repo_id=args.repo_id))
    prepare_local_stage(stage0, replace_existing=args.replace_existing, run_id=run_id)
    for rank, node in enumerate(args.nodes[1:], start=1):
        host = host_for(node, args.ssh_host_template)
        stage_dir = template(args.stage_dir_template, node=node, rank=rank, run_id=run_id, repo_id=args.repo_id)
        handoff_dir = template(args.handoff_dir_template, node=node, rank=rank, run_id=run_id, repo_id=args.repo_id)
        run_passthrough(scp_argv(str(this_script), f"{host}:{remote_script}"))
        run_passthrough(scp_argv(str(local_manifest), f"{host}:{remote_manifest}"))
        remote_prepare(host, stage_dir, handoff_dir, replace_existing=args.replace_existing, run_id=run_id)
    workers: list[tuple[str, int, str]] = []
    for rank, node in enumerate(args.nodes[1:], start=1):
        host = host_for(node, args.ssh_host_template)
        log_path = f"/home/{node}/ds4_logs/waterfall/{run_id}_rank{rank}.log"
        pid = start_worker(host, rank, remote_script, remote_manifest, log_path)
        workers.append((host, pid, log_path))
        print(json.dumps({"status": "worker_started", "rank": rank, "node": node, "pid": pid, "log": log_path}))
    first_handoff = template(args.handoff_dir_template, node=args.nodes[1], rank=1, run_id=run_id, repo_id=args.repo_id) if len(args.nodes) > 1 else ""
    first_host = host_for(args.nodes[1], args.ssh_host_template) if len(args.nodes) > 1 else ""
    first_node = args.nodes[1] if len(args.nodes) > 1 else ""
    if args.watch_source:
        orchestrator_stream_files(files, source_dir=source_dir, stage0=stage0, first_node=first_node, first_host=first_host, first_handoff=first_handoff, manifest=manifest, args=args)
    else:
        for item in files:
            src = source_dir / item.rel
            if max(item.needed_ranks) > 0:
                send_file(src, rel=item.rel, size=item.size, source_node=args.nodes[0], source_base=str(source_dir), dest_node=first_node, host=first_host, dest_base=first_handoff, manifest=manifest)
            if 0 in item.needed_ranks:
                install_local(src, stage0 / item.rel, item.size, link_mode=args.link_mode)
    write_marker(stage0, manifest, 0, files)
    for host, pid, log_path in workers:
        wait_worker(host, pid, log_path)
    print(json.dumps({"status": "complete", "run_id": run_id}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-full-dir", help="Full model dir on rank0, usually external NVMe")
    parser.add_argument("--repo-id", required=False, default="")
    parser.add_argument("--nodes", default="spark0,spark1,spark2,spark3,spark4,spark5,spark6,spark7,spark8,spark9,sparka,sparkb,sparkc")
    parser.add_argument("--partition", required=False, default="6,4,4,4,4,8,8,8,8,8,4,4,8")
    parser.add_argument("--stage-dir-template", default=DEFAULT_STAGE_TEMPLATE)
    parser.add_argument("--handoff-dir-template", default=DEFAULT_HANDOFF_TEMPLATE)
    parser.add_argument("--ssh-host-template", default="{node}")
    parser.add_argument("--layer-regex", default=DEFAULT_LAYER_REGEX)
    parser.add_argument("--extra-safetensors", choices=("all", "rank0", "none"), default="all")
    parser.add_argument("--link-mode", choices=("auto", "copy", "hardlink"), default="auto")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--remote-script", default=DEFAULT_REMOTE_SCRIPT)
    parser.add_argument("--wait-timeout-s", type=int, default=0)
    parser.add_argument("--poll-s", type=float, default=1.0)
    parser.add_argument("--transfer-mode", choices=("fast-copy", "rsync"), default="fast-copy")
    parser.add_argument("--remote-v2-dir", default=DEFAULT_REMOTE_V2_DIR)
    parser.add_argument("--transfer-topology", default=DEFAULT_TRANSFER_TOPOLOGY)
    parser.add_argument("--fast-copy-jobs-per-edge", type=int, default=16)
    parser.add_argument("--fast-copy-port-base", type=int, default=49300)
    parser.add_argument("--fast-copy-timeout-s", type=int, default=7200)
    parser.add_argument("--striped-file-stripes", type=int, default=8)
    parser.add_argument("--striped-file-threshold-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--rsync-bwlimit", default="")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--cleanup-handoff", action="store_true", default=True)
    parser.add_argument("--keep-handoff", action="store_false", dest="cleanup_handoff")
    parser.add_argument("--skip-cache", action="store_true", default=True)
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--watch-source", action="store_true", help="Execute a streaming waterfall and forward source files as they appear")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--worker-rank", type=int, default=-1)
    parser.add_argument("--manifest", default="")
    args = parser.parse_args()
    if args.worker:
        if not args.manifest or args.worker_rank < 0:
            raise SystemExit("--worker requires --manifest and --worker-rank")
        return worker_main(args)
    if not args.source_full_dir:
        raise SystemExit("--source-full-dir is required")
    if not args.repo_id:
        source = Path(args.source_full_dir)
        args.repo_id = "/".join(source.parts[-2:]) if len(source.parts) >= 2 else source.name
    return orchestrator_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
