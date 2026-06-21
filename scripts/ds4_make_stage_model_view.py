#!/usr/bin/env python3
"""Create a pipeline-rank-local hardlink view of a sharded HF model tree."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
from pathlib import Path


def parse_partition(text: str) -> list[int]:
    out = [int(item) for item in text.split(",") if item.strip()]
    if not out or any(item <= 0 for item in out):
        raise SystemExit("partition must be a comma-separated list of positive integers")
    return out


def stage_bounds(partition: list[int], rank: int) -> tuple[int, int]:
    if rank < 0 or rank >= len(partition):
        raise SystemExit("rank outside partition width")
    start = sum(partition[:rank])
    return (start, start + partition[rank])


def required_shards(model_dir: Path, partition: list[int], rank: int, layer_regex: str) -> set[str]:
    index_path = model_dir / "model.safetensors.index.json"
    if not index_path.exists():
        raise SystemExit(f"missing index: {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    weight_map = data.get("weight_map")
    if not isinstance(weight_map, dict):
        raise SystemExit("index does not contain a weight_map object")
    rex = re.compile(layer_regex)
    start, end = stage_bounds(partition, rank)
    shards: set[str] = set()
    shared: set[str] = set()
    for tensor, shard in weight_map.items():
        match = rex.search(str(tensor))
        if match is None:
            shared.add(str(shard))
            continue
        layer = int(match.group(1))
        if start <= layer < end:
            shards.add(str(shard))
    shards.update(shared)
    return shards


def link_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.link(src, dst)


def link_tree(src: Path, dst: Path) -> None:
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            link_file(Path(root) / name, dst / rel / name)
        for name in dirs:
            (dst / rel / name).mkdir(parents=True, exist_ok=True)


def build_view(model_dir: Path, temp_dir: Path, required: set[str], args: argparse.Namespace) -> None:
    temp_dir.mkdir(parents=True)
    for item in model_dir.iterdir():
        if item.name == temp_dir.name:
            continue
        if item.is_file():
            if item.suffix == ".safetensors" and item.name not in required:
                continue
            link_file(item, temp_dir / item.name)
        elif item.is_dir():
            if item.name == ".cache" and args.skip_cache:
                continue
            link_tree(item, temp_dir / item.name)
    marker = {
        "format": "ds4-stage-model-view-v1",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_full_dir": str(model_dir),
        "rank": args.rank,
        "partition": args.partition,
        "layer_regex": args.layer_regex,
        "required_shards": sorted(required),
    }
    (temp_dir / ".ds4_stage_view.json").write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--rank", type=int, required=True)
    parser.add_argument("--partition", required=True)
    parser.add_argument("--layer-regex", default=r"model\.layers\.(\d+)\.")
    parser.add_argument("--skip-cache", action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    model_dir = Path(args.model_dir)
    partition = parse_partition(args.partition)
    args.partition = partition
    if not model_dir.is_dir():
        raise SystemExit(f"missing model dir: {model_dir}")
    if (model_dir / ".ds4_stage_view.json").exists():
        print(json.dumps({"status": "already_view", "model_dir": str(model_dir)}))
        return 0
    required = required_shards(model_dir, partition, args.rank, args.layer_regex)
    missing = sorted(name for name in required if not (model_dir / name).exists())
    if missing:
        raise SystemExit("missing required shards: " + ",".join(missing[:8]))
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    old_dir = model_dir.with_name(model_dir.name + f".full-archive-src-{stamp}")
    temp_dir = model_dir.with_name(model_dir.name + f".stage{args.rank}.tmp-{stamp}")
    if old_dir.exists() or temp_dir.exists():
        raise SystemExit("refusing to overwrite existing temp/archive dir")
    plan = {
        "status": "planned",
        "model_dir": str(model_dir),
        "old_dir": str(old_dir),
        "temp_dir": str(temp_dir),
        "rank": args.rank,
        "stage_bounds": stage_bounds(partition, args.rank),
        "required_shards": len(required),
    }
    if args.dry_run:
        print(json.dumps(plan, sort_keys=True))
        return 0
    build_view(model_dir, temp_dir, required, args)
    model_dir.rename(old_dir)
    temp_dir.rename(model_dir)
    print(json.dumps({**plan, "status": "converted"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
