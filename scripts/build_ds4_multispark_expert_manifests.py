#!/usr/bin/env python3
"""Emit per-rank DS4 expert residency manifests from an owner table."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        obj = json.loads(f.read())
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object in {path}")
    return(obj)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if len(chunk) == 0:
                break
            h.update(chunk)
    return(h.hexdigest())


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _validate_owner_table(obj: dict[str, Any]) -> list[list[int]]:
    if obj.get("schema") != "ds4_expert_owner_table_v1":
        raise ValueError("owner table schema must be ds4_expert_owner_table_v1")
    experts = int(obj.get("experts", 0))
    sparks = int(obj.get("sparks", 0))
    layers = int(obj.get("num_layers", 0))
    raw = obj.get("owner_table")
    if int(experts) <= 0:
        raise ValueError("owner table experts must be > 0")
    if int(sparks) <= 0:
        raise ValueError("owner table sparks must be > 0")
    if int(layers) <= 0:
        raise ValueError("owner table num_layers must be > 0")
    if not isinstance(raw, list) or len(raw) != int(layers):
        raise ValueError("owner_table row count must match num_layers")
    table: list[list[int]] = []
    for layer, row in enumerate(raw):
        if not isinstance(row, list) or len(row) != int(experts):
            raise ValueError(f"owner_table[{int(layer)}] must contain {int(experts)} owners")
        clean: list[int] = []
        for expert, owner in enumerate(row):
            owner_i = int(owner)
            if owner_i < 0 or owner_i >= int(sparks):
                raise ValueError(f"owner_table[{int(layer)}][{int(expert)}] owner {int(owner_i)} is outside 0..{int(sparks) - 1}")
            clean.append(int(owner_i))
        table.append(clean)
    return(table)


def _owned_experts_by_layer(table: list[list[int]], rank: int) -> list[list[int]]:
    owned: list[list[int]] = []
    for row in table:
        owned.append([int(expert) for expert, owner in enumerate(row) if int(owner) == int(rank)])
    return(owned)


def _rank_summary(owned: list[list[int]]) -> dict[str, Any]:
    counts = [len(row) for row in owned]
    total = int(sum(counts))
    return(
        {
            "owned_counts_by_layer": counts,
            "total_owned_layer_experts": int(total),
            "min_owned_per_layer": int(min(counts)) if len(counts) != 0 else 0,
            "median_owned_per_layer": float(statistics.median(counts)) if len(counts) != 0 else 0.0,
            "max_owned_per_layer": int(max(counts)) if len(counts) != 0 else 0,
        }
    )


def _build_rank_manifest(
    owner_obj: dict[str, Any],
    owner_path: Path,
    owner_hash: str,
    table: list[list[int]],
    rank: int,
) -> dict[str, Any]:
    owned = _owned_experts_by_layer(table, int(rank))
    summary = _rank_summary(owned)
    return(
        {
            "schema": "ds4_multispark_owned_expert_manifest_v1",
            "rank": int(rank),
            "world_size": int(owner_obj.get("sparks", 0)),
            "num_layers": int(owner_obj.get("num_layers", 0)),
            "experts": int(owner_obj.get("experts", 0)),
            "logical_lanes": int(owner_obj.get("logical_lanes", 0)),
            "strategy": str(owner_obj.get("strategy", "")),
            "owner_table_sha256": str(owner_hash),
            "source_owner_table_json": str(owner_path),
            "load_contract": {
                "gpu_resident_moe": "load only the owned expert tensors listed in owned_experts_by_layer",
                "routing": "owner_table[layer][expert_id] selects the rank that owns that expert output",
                "model_storage": "the full GGUF may exist on local disk or CPU mmap, but GPU residency is per-rank",
                "shared_runtime": "dense weights, KV cache, token buffers, and transport buffers are separate runtime contracts",
            },
            **summary,
            "owned_experts_by_layer": owned,
        }
    )


def _validate_partition(manifests: list[dict[str, Any]], experts: int, layers: int) -> None:
    for layer in range(int(layers)):
        seen: set[int] = set()
        for manifest in manifests:
            owned = manifest.get("owned_experts_by_layer")
            if not isinstance(owned, list):
                raise ValueError("rank manifest is missing owned_experts_by_layer")
            row = owned[int(layer)]
            if not isinstance(row, list):
                raise ValueError("rank manifest owned_experts_by_layer row is not a list")
            for expert in row:
                expert_i = int(expert)
                if expert_i < 0 or expert_i >= int(experts):
                    raise ValueError(f"manifest expert {int(expert_i)} is outside 0..{int(experts) - 1}")
                if int(expert_i) in seen:
                    raise ValueError(f"expert {int(expert_i)} appears in multiple rank manifests for layer {int(layer)}")
                seen.add(int(expert_i))
        if len(seen) != int(experts):
            raise ValueError(f"layer {int(layer)} partition covers {len(seen)} experts, expected {int(experts)}")


def build_manifests(owner_path: Path, out_dir: Path, prefix: str, index_name: str) -> dict[str, Any]:
    owner_obj = _read_json(owner_path)
    table = _validate_owner_table(owner_obj)
    owner_hash = _sha256(owner_path)
    world_size = int(owner_obj.get("sparks", 0))
    experts = int(owner_obj.get("experts", 0))
    layers = int(owner_obj.get("num_layers", 0))
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests: list[dict[str, Any]] = []
    ranks: list[dict[str, Any]] = []
    for rank in range(int(world_size)):
        manifest = _build_rank_manifest(owner_obj, owner_path, owner_hash, table, int(rank))
        manifests.append(manifest)
    _validate_partition(manifests, int(experts), int(layers))
    for manifest in manifests:
        rank = int(manifest["rank"])
        rel = f"{str(prefix)}-{rank:03d}.json"
        _write_json(out_dir / rel, manifest)
        ranks.append(
            {
                "rank": int(rank),
                "path": rel,
                "total_owned_layer_experts": int(manifest["total_owned_layer_experts"]),
                "min_owned_per_layer": int(manifest["min_owned_per_layer"]),
                "median_owned_per_layer": float(manifest["median_owned_per_layer"]),
                "max_owned_per_layer": int(manifest["max_owned_per_layer"]),
            }
        )
    index = {
        "schema": "ds4_multispark_owned_expert_manifest_index_v1",
        "world_size": int(world_size),
        "num_layers": int(layers),
        "experts": int(experts),
        "logical_lanes": int(owner_obj.get("logical_lanes", 0)),
        "strategy": str(owner_obj.get("strategy", "")),
        "owner_table_sha256": str(owner_hash),
        "source_owner_table_json": str(owner_path),
        "load_contract": {
            "intent": "preload exactly the MoE expert slices each Spark owns, not every model on every Spark",
            "routing": "dispatch expert work to the owning rank using the source owner table",
        },
        "table_balance": owner_obj.get("table_balance", {}),
        "same_spark": owner_obj.get("same_spark", {}),
        "ranks": ranks,
    }
    _write_json(out_dir / str(index_name), index)
    return(index)


def _print_summary(index: dict[str, Any], out_dir: Path) -> None:
    print(
        f"manifests={out_dir} world_size={index.get('world_size')} "
        f"layers={index.get('num_layers')} experts={index.get('experts')} strategy={index.get('strategy')}"
    )
    for rank in index.get("ranks", []):
        if not isinstance(rank, dict):
            continue
        print(
            f"rank={rank.get('rank')} path={rank.get('path')} "
            f"owned_total={rank.get('total_owned_layer_experts')} "
            f"per_layer={rank.get('min_owned_per_layer')}/{rank.get('median_owned_per_layer')}/{rank.get('max_owned_per_layer')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-table-json", required=True, help="JSON emitted by build_ds4_expert_owner_table.py.")
    parser.add_argument("--out-dir", required=True, help="Directory for manifest index and per-rank files.")
    parser.add_argument("--rank-prefix", default="rank")
    parser.add_argument("--index-name", default="manifest.json")
    args = parser.parse_args()
    index = build_manifests(
        Path(str(args.owner_table_json)),
        Path(str(args.out_dir)),
        str(args.rank_prefix),
        str(args.index_name),
    )
    _print_summary(index, Path(str(args.out_dir)))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
