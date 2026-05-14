#!/usr/bin/env python3
"""Analyze conditional DS4 expert transitions between adjacent layers."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

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


def _fmt_pct(x: object) -> str:
    if not isinstance(x, (int, float)):
        return("0.00%")
    return(f"{100.0 * float(x):.2f}%")


def _print_text(summary: dict[str, object], top_current: int) -> None:
    cond = summary.get("conditional_summary")
    same = summary.get("same_spark")
    if not isinstance(cond, dict):
        cond = {}
    if not isinstance(same, dict):
        same = {}
    print(
        f"layers={summary.get('num_layers')} layer_pairs={summary.get('layer_pairs')} "
        f"tokens_per_layer={summary.get('tokens_per_layer')} topk={summary.get('topk')} "
        f"experts={summary.get('experts')} sparks={summary.get('sparks')}"
    )
    print(f"pair_transitions={summary.get('pair_transitions')} invalid_expert_ids={summary.get('invalid_expert_ids')}")
    print(
        "conditional_next_expert "
        f"top1={_fmt_pct(cond.get('weighted_top1_mass'))} "
        f"top4={_fmt_pct(cond.get('weighted_top4_mass'))} "
        f"top8={_fmt_pct(cond.get('weighted_top8_mass'))} "
        f"entropy_norm={_fmt_pct(cond.get('weighted_normalized_entropy'))}"
    )
    print(
        "same_spark "
        f"mod_lane={_fmt_pct(same.get('mod_lane_same_spark_rate'))} "
        f"affinity_table={_fmt_pct(same.get('affinity_same_spark_rate'))} "
        f"cross_reduction={_fmt_pct(same.get('affinity_cross_spark_reduction'))}"
    )
    rows = summary.get("top_current_experts")
    if not isinstance(rows, list):
        return
    print("top_current_experts current transitions top1 top4 top_next")
    for row in rows[: max(1, int(top_current))]:
        if not isinstance(row, dict):
            continue
        top_next = row.get("top_next_experts")
        next_bits = []
        if isinstance(top_next, list):
            for nxt in top_next[:4]:
                if not isinstance(nxt, dict):
                    continue
                next_bits.append(f"{nxt.get('expert')}:{_fmt_pct(nxt.get('prob'))}")
        print(
            f"{row.get('current_expert')} {row.get('transitions')} "
            f"{_fmt_pct(row.get('top1_mass'))} {_fmt_pct(row.get('top4_mass'))} "
            f"{','.join(next_bits)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-dir", required=True, help="Directory containing ffn_moe_topk-<layer>_pos<pos>.i32 dumps.")
    parser.add_argument("--pos", type=int, default=-1, help="Dump position index (-1 = infer, requires a single pos in dump-dir).")
    parser.add_argument("--topk", type=int, default=6)
    parser.add_argument("--experts", type=int, default=256)
    parser.add_argument("--logical-lanes", type=int, default=32)
    parser.add_argument("--sparks", type=int, default=8)
    parser.add_argument("--top-masses", default="1,4,8,16,32")
    parser.add_argument("--top-next", type=int, default=8)
    parser.add_argument("--strict-expert-ids", type=int, default=1)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--full-json", action="store_true", help="Print/write the full report including routing tables.")
    parser.add_argument("--top-current", type=int, default=8)
    args = parser.parse_args()

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

    top_masses = tuple(int(x) for x in str(args.top_masses).split(",") if str(x).strip() != "")
    meta, layers = ds4_topk_dump.load_ds4_ffn_moe_topk_dump_layers(str(dump_dir), pos=int(pos), topk=int(args.topk))
    cfg = expert_transition_probe.ExpertTransitionProbeConfig(
        experts=int(args.experts),
        topk=int(args.topk),
        logical_lanes=int(args.logical_lanes),
        sparks=int(args.sparks),
        top_masses=top_masses,
        top_next=int(args.top_next),
        strict_expert_ids=bool(int(args.strict_expert_ids) != 0),
    )
    result = expert_transition_probe.analyze_expert_transitions(layers, cfg)
    result["dump_dir"] = str(dump_dir)
    result["pos"] = int(meta.pos)
    output = result if bool(args.full_json) else expert_transition_probe.as_compact_report(result, top_current=int(args.top_current))
    if str(args.json_out).strip() != "":
        Path(str(args.json_out)).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if bool(args.full_json):
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        _print_text(output, int(args.top_current))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
