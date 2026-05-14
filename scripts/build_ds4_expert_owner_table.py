#!/usr/bin/env python3
"""Build a table-driven DS4 expert owner map from ffn_moe_topk dumps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.scheduler import ds4_topk_dump
from sim.scheduler import expert_transition_probe


_DUMP_RE = re.compile(r"ffn_moe_topk-(\d+)_pos(\d+)\.i32$")


def _available_positions(dump_dir: Path) -> list[int]:
    positions: set[int] = set()
    for path in dump_dir.glob("*ffn_moe_topk-*_pos*.i32"):
        m = _DUMP_RE.search(path.name)
        if m is not None:
            positions.add(int(m.group(2)))
    return(sorted(positions))


def _load_layers(args: argparse.Namespace) -> tuple[ds4_topk_dump.Ds4TopkDumpMeta, list[list[list[int]]]]:
    dump_dir = Path(str(args.dump_dir))
    if not dump_dir.exists():
        raise SystemExit(f"dump-dir does not exist: {dump_dir}")
    pos = int(args.pos)
    if pos < 0:
        positions = _available_positions(dump_dir)
        if len(positions) == 0:
            raise SystemExit(f"no ffn_moe_topk dumps found in {dump_dir}")
        if len(positions) != 1:
            raise SystemExit(f"dump-dir contains multiple pos values {positions}; pass --pos to select one")
        pos = int(positions[0])
    return(ds4_topk_dump.load_ds4_ffn_moe_topk_dump_layers(str(dump_dir), pos=int(pos), topk=int(args.topk)))


def _write_json(path: str, obj: dict[str, Any]) -> None:
    text = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    if str(path) == "-":
        print(text, end="")
        return
    Path(str(path)).write_text(text, encoding="utf-8")


def _write_c_header(path: str, artifact: dict[str, Any], symbol: str) -> None:
    table = artifact.get("owner_table")
    if not isinstance(table, list):
        raise ValueError("artifact owner_table is missing")
    layers = int(artifact.get("num_layers", 0))
    experts = int(artifact.get("experts", 0))
    lines = []
    lines.append("#pragma once")
    lines.append("#include <stdint.h>")
    lines.append("")
    lines.append(f"#define {str(symbol).upper()}_LAYERS {int(layers)}")
    lines.append(f"#define {str(symbol).upper()}_EXPERTS {int(experts)}")
    lines.append(f"static const uint8_t {str(symbol)}[{int(layers)}][{int(experts)}] = {{")
    for layer, row in enumerate(table):
        if not isinstance(row, list):
            raise ValueError(f"owner table row {int(layer)} is not a list")
        vals = ",".join(str(int(x)) for x in row)
        comma = "," if int(layer) + 1 < int(layers) else ""
        lines.append(f"    {{{vals}}}{comma}")
    lines.append("};")
    lines.append("")
    text = "\n".join(lines)
    if str(path) == "-":
        print(text)
        return
    Path(str(path)).write_text(text, encoding="utf-8")


def _print_summary(artifact: dict[str, Any]) -> None:
    same = artifact.get("same_spark")
    balance = artifact.get("table_balance")
    if not isinstance(same, dict):
        same = {}
    if not isinstance(balance, dict):
        balance = {}
    print(
        f"strategy={artifact.get('strategy')} layers={artifact.get('num_layers')} "
        f"experts={artifact.get('experts')} sparks={artifact.get('sparks')}"
    )
    print(
        f"same_spark_mod={float(same.get('mod_lane_same_spark_rate', 0.0)):.6f} "
        f"same_spark_table={float(same.get('affinity_same_spark_rate', 0.0)):.6f} "
        f"cross_reduction={float(same.get('affinity_cross_spark_reduction', 0.0)):.6f}"
    )
    imb = balance.get("imbalance")
    if isinstance(imb, dict):
        print(
            f"balance_imbalance_min={float(imb.get('min', 0.0)):.1f} "
            f"median={float(imb.get('median', 0.0)):.1f} "
            f"max={float(imb.get('max', 0.0)):.1f}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-dir", required=True, help="Directory containing ffn_moe_topk-<layer>_pos<pos>.i32 dumps.")
    parser.add_argument("--pos", type=int, default=-1)
    parser.add_argument("--topk", type=int, default=6)
    parser.add_argument("--experts", type=int, default=256)
    parser.add_argument("--logical-lanes", type=int, default=32)
    parser.add_argument("--sparks", type=int, default=8)
    parser.add_argument("--strategy", choices=("affinity", "mod_lane"), default="affinity")
    parser.add_argument("--json-out", default="-")
    parser.add_argument("--c-header-out", default="")
    parser.add_argument("--c-symbol", default="ds4_expert_owner_table")
    parser.add_argument("--strict-expert-ids", type=int, default=1)
    args = parser.parse_args()

    meta, layers = _load_layers(args)
    cfg = expert_transition_probe.ExpertTransitionProbeConfig(
        experts=int(args.experts),
        topk=int(args.topk),
        logical_lanes=int(args.logical_lanes),
        sparks=int(args.sparks),
        strict_expert_ids=bool(int(args.strict_expert_ids) != 0),
    )
    result = expert_transition_probe.analyze_expert_transitions(layers, cfg)
    artifact = expert_transition_probe.build_owner_table_artifact(result, strategy=str(args.strategy))
    artifact["dump_dir"] = str(args.dump_dir)
    artifact["pos"] = int(meta.pos)
    _write_json(str(args.json_out), artifact)
    if str(args.c_header_out).strip() != "":
        _write_c_header(str(args.c_header_out), artifact, str(args.c_symbol))
    if str(args.json_out) != "-":
        _print_summary(artifact)
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
