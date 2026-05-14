#!/usr/bin/env python3
"""Compute a DS4 expert-shard best-case ceiling and expert_id % lane map."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class CeilingConfig:
    experts: int = 256
    logical_lanes: int = 32
    sparks: int = 8
    layers: int = 43
    topk: int = 6
    pairs_per_s_per_spark: float = 159700.0
    ffn_token_layer_per_s_per_spark: float = 24007.073
    batch_decode_tok_s_per_spark: float = 409.0
    single_stream_tok_s_per_spark: float = 13.3
    network_efficiency: float = 1.0
    mtp_multiplier: float = 1.0


def _require_positive(name: str, value: float) -> None:
    if float(value) <= 0.0:
        raise ValueError(f"{name} must be > 0")


def validate_config(cfg: CeilingConfig) -> None:
    _require_positive("experts", cfg.experts)
    _require_positive("logical_lanes", cfg.logical_lanes)
    _require_positive("sparks", cfg.sparks)
    _require_positive("layers", cfg.layers)
    _require_positive("topk", cfg.topk)
    _require_positive("pairs_per_s_per_spark", cfg.pairs_per_s_per_spark)
    _require_positive("network_efficiency", cfg.network_efficiency)
    _require_positive("mtp_multiplier", cfg.mtp_multiplier)
    if int(cfg.logical_lanes) > int(cfg.experts):
        raise ValueError("logical_lanes must be <= experts")
    if float(cfg.network_efficiency) > 1.0:
        raise ValueError("network_efficiency must be <= 1.0")


def expert_lane(expert_id: int, logical_lanes: int) -> int:
    return(int(expert_id) % int(logical_lanes))


def lane_spark_rank(lane: int, logical_lanes: int, sparks: int) -> int:
    return((int(lane) * int(sparks)) // int(logical_lanes))


def build_lane_map(cfg: CeilingConfig) -> List[Dict[str, Any]]:
    validate_config(cfg)
    lanes: List[Dict[str, Any]] = []
    for lane in range(int(cfg.logical_lanes)):
        experts = [eid for eid in range(int(cfg.experts)) if expert_lane(eid, int(cfg.logical_lanes)) == lane]
        lanes.append(
            {
                "lane": int(lane),
                "spark_rank": lane_spark_rank(lane, int(cfg.logical_lanes), int(cfg.sparks)),
                "expert_count": int(len(experts)),
                "expert_ids": experts,
            }
        )
    return(lanes)


def build_spark_summary(lanes: List[Dict[str, Any]], sparks: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for spark in range(int(sparks)):
        owned_lanes = [row for row in lanes if int(row["spark_rank"]) == int(spark)]
        expert_ids: List[int] = []
        for row in owned_lanes:
            expert_ids.extend(int(eid) for eid in row["expert_ids"])
        out.append(
            {
                "spark_rank": int(spark),
                "lane_ids": [int(row["lane"]) for row in owned_lanes],
                "expert_count": int(len(expert_ids)),
                "expert_ids": sorted(expert_ids),
            }
        )
    return(out)


def compute_ceilings(cfg: CeilingConfig) -> Dict[str, Any]:
    validate_config(cfg)
    layer_pairs_per_output_token = float(cfg.layers) * float(cfg.topk)
    moe_tok_s_per_spark = float(cfg.pairs_per_s_per_spark) / layer_pairs_per_output_token
    moe_tok_s_cluster = moe_tok_s_per_spark * float(cfg.sparks) * float(cfg.network_efficiency) * float(cfg.mtp_multiplier)
    ffn_tok_s_per_spark = float(cfg.ffn_token_layer_per_s_per_spark) / float(cfg.layers)
    ffn_tok_s_cluster = ffn_tok_s_per_spark * float(cfg.sparks) * float(cfg.network_efficiency) * float(cfg.mtp_multiplier)
    batch_tok_s_cluster = float(cfg.batch_decode_tok_s_per_spark) * float(cfg.sparks) * float(cfg.network_efficiency) * float(cfg.mtp_multiplier)
    single_stream_tok_s_cluster = float(cfg.single_stream_tok_s_per_spark) * float(cfg.sparks) * float(cfg.network_efficiency) * float(cfg.mtp_multiplier)
    return(
        {
            "layer_pairs_per_output_token": layer_pairs_per_output_token,
            "moe_only_tok_s_per_spark": moe_tok_s_per_spark,
            "moe_only_tok_s_cluster": moe_tok_s_cluster,
            "ffn_envelope_tok_s_per_spark": ffn_tok_s_per_spark,
            "ffn_envelope_tok_s_cluster": ffn_tok_s_cluster,
            "batched_layer_tok_s_per_spark": float(cfg.batch_decode_tok_s_per_spark),
            "batched_layer_tok_s_cluster": batch_tok_s_cluster,
            "single_stream_tok_s_per_spark": float(cfg.single_stream_tok_s_per_spark),
            "single_stream_tok_s_cluster": single_stream_tok_s_cluster,
            "network_efficiency": float(cfg.network_efficiency),
            "mtp_multiplier": float(cfg.mtp_multiplier),
        }
    )


def build_report(cfg: CeilingConfig) -> Dict[str, Any]:
    lanes = build_lane_map(cfg)
    return(
        {
            "schema": "ds4_expert_mod_lane_ceiling_v1",
            "config": cfg.__dict__,
            "ceilings": compute_ceilings(cfg),
            "lane_map": lanes,
            "spark_summary": build_spark_summary(lanes, int(cfg.sparks)),
        }
    )


def _fmt(value: float) -> str:
    if abs(float(value)) >= 100.0:
        return(f"{float(value):,.1f}")
    return(f"{float(value):.3f}")


def print_text_report(report: Dict[str, Any], show_experts: bool) -> None:
    cfg = report["config"]
    ceilings = report["ceilings"]
    print(f"experts={cfg['experts']} logical_lanes={cfg['logical_lanes']} sparks={cfg['sparks']} layers={cfg['layers']} topk={cfg['topk']}")
    print(f"lane_rule=expert_id % {cfg['logical_lanes']}; spark_rank=floor(lane * sparks / logical_lanes)")
    print(f"layer_pairs_per_output_token={_fmt(ceilings['layer_pairs_per_output_token'])}")
    print("ceiling tok/s:")
    print(f"  moe_only_per_spark={_fmt(ceilings['moe_only_tok_s_per_spark'])}")
    print(f"  moe_only_cluster={_fmt(ceilings['moe_only_tok_s_cluster'])}")
    print(f"  ffn_envelope_per_spark={_fmt(ceilings['ffn_envelope_tok_s_per_spark'])}")
    print(f"  ffn_envelope_cluster={_fmt(ceilings['ffn_envelope_tok_s_cluster'])}")
    print(f"  batched_layer_per_spark={_fmt(ceilings['batched_layer_tok_s_per_spark'])}")
    print(f"  batched_layer_cluster={_fmt(ceilings['batched_layer_tok_s_cluster'])}")
    print(f"  single_stream_per_spark={_fmt(ceilings['single_stream_tok_s_per_spark'])}")
    print(f"  single_stream_cluster={_fmt(ceilings['single_stream_tok_s_cluster'])}")
    print("spark lane ownership:")
    for row in report["spark_summary"]:
        print(f"  spark{row['spark_rank']}: lanes={row['lane_ids']} expert_count={row['expert_count']}")
    if not show_experts:
        return
    print("lane expert ids:")
    for row in report["lane_map"]:
        print(f"  lane{row['lane']:02d} spark{row['spark_rank']}: {row['expert_ids']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experts", type=int, default=256)
    parser.add_argument("--logical-lanes", type=int, default=32)
    parser.add_argument("--sparks", type=int, default=8)
    parser.add_argument("--layers", type=int, default=43)
    parser.add_argument("--topk", type=int, default=6)
    parser.add_argument("--pairs-per-s-per-spark", type=float, default=159700.0)
    parser.add_argument("--ffn-token-layer-per-s-per-spark", type=float, default=24007.073)
    parser.add_argument("--batch-decode-tok-s-per-spark", type=float, default=409.0)
    parser.add_argument("--single-stream-tok-s-per-spark", type=float, default=13.3)
    parser.add_argument("--network-efficiency", type=float, default=1.0)
    parser.add_argument("--mtp-multiplier", type=float, default=1.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--show-experts", action="store_true")
    args = parser.parse_args()
    cfg = CeilingConfig(
        experts=int(args.experts),
        logical_lanes=int(args.logical_lanes),
        sparks=int(args.sparks),
        layers=int(args.layers),
        topk=int(args.topk),
        pairs_per_s_per_spark=float(args.pairs_per_s_per_spark),
        ffn_token_layer_per_s_per_spark=float(args.ffn_token_layer_per_s_per_spark),
        batch_decode_tok_s_per_spark=float(args.batch_decode_tok_s_per_spark),
        single_stream_tok_s_per_spark=float(args.single_stream_tok_s_per_spark),
        network_efficiency=float(args.network_efficiency),
        mtp_multiplier=float(args.mtp_multiplier),
    )
    report = build_report(cfg)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_text_report(report, bool(args.show_experts))
    return(0)


if __name__ == "__main__":
    raise SystemExit(main())
