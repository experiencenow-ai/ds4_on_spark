from __future__ import annotations

import dataclasses
import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class ExpertTransitionProbeConfig:
    experts: int = 256
    topk: int = 6
    logical_lanes: int = 32
    sparks: int = 8
    top_masses: Tuple[int, ...] = (1, 4, 8, 16, 32)
    top_next: int = 8
    strict_expert_ids: bool = True


def _summary(values: Iterable[float]) -> Dict[str, float]:
    vals = [float(v) for v in values]
    if len(vals) == 0:
        return({"min": 0.0, "median": 0.0, "mean": 0.0, "max": 0.0})
    return(
        {
            "min": float(min(vals)),
            "median": float(statistics.median(vals)),
            "mean": float(sum(vals) / float(len(vals))),
            "max": float(max(vals)),
        }
    )


def _validate_config(cfg: ExpertTransitionProbeConfig) -> None:
    if int(cfg.experts) <= 0:
        raise ValueError("experts must be > 0")
    if int(cfg.topk) <= 0:
        raise ValueError("topk must be > 0")
    if int(cfg.logical_lanes) <= 0:
        raise ValueError("logical_lanes must be > 0")
    if int(cfg.sparks) <= 0:
        raise ValueError("sparks must be > 0")
    if int(cfg.logical_lanes) > int(cfg.experts):
        raise ValueError("logical_lanes must be <= experts")
    if len(cfg.top_masses) == 0:
        raise ValueError("top_masses must be non-empty")
    for n in cfg.top_masses:
        if int(n) <= 0:
            raise ValueError("top_masses entries must be > 0")
    if int(cfg.top_next) <= 0:
        raise ValueError("top_next must be > 0")


def _validate_layers(layers: Sequence[Sequence[Sequence[int]]], cfg: ExpertTransitionProbeConfig) -> Tuple[int, int]:
    if len(layers) < 2:
        raise ValueError("at least two layers are required for transition analysis")
    tokens_per_layer = -1
    invalid = 0
    for layer_rows in layers:
        if tokens_per_layer < 0:
            tokens_per_layer = len(layer_rows)
        elif int(tokens_per_layer) != len(layer_rows):
            raise ValueError("each layer must have the same number of rows")
        for row in layer_rows:
            if len(row) != int(cfg.topk):
                raise ValueError("each row must have exactly topk entries")
            for expert in row:
                if int(expert) < 0 or int(expert) >= int(cfg.experts):
                    invalid += 1
    if int(tokens_per_layer) <= 0:
        raise ValueError("tokens_per_layer must be > 0")
    if bool(cfg.strict_expert_ids) and int(invalid) != 0:
        raise ValueError("encountered out-of-range expert IDs; pass strict_expert_ids=False to ignore")
    return(int(tokens_per_layer), int(invalid))


def lane_for_expert(expert_id: int, logical_lanes: int) -> int:
    return(int(expert_id) % int(logical_lanes))


def spark_for_lane(lane: int, logical_lanes: int, sparks: int) -> int:
    return((int(lane) * int(sparks)) // int(logical_lanes))


def build_mod_lane_spark_table(cfg: ExpertTransitionProbeConfig) -> List[int]:
    _validate_config(cfg)
    out: List[int] = []
    for expert_id in range(int(cfg.experts)):
        lane = lane_for_expert(int(expert_id), int(cfg.logical_lanes))
        out.append(spark_for_lane(int(lane), int(cfg.logical_lanes), int(cfg.sparks)))
    return(out)


def _spark_capacities(experts: int, sparks: int) -> List[int]:
    base = int(experts) // int(sparks)
    rem = int(experts) % int(sparks)
    return([int(base) + (1 if s < int(rem) else 0) for s in range(int(sparks))])


def _sorted_sparks_by_inbound(row: Sequence[int]) -> List[int]:
    return(sorted(range(len(row)), key=lambda s: (-int(row[int(s)]), int(s))))


def _assign_next_layer_by_inbound(inbound: Sequence[Sequence[int]], cfg: ExpertTransitionProbeConfig) -> List[int]:
    capacities = _spark_capacities(int(cfg.experts), int(cfg.sparks))
    ranked_experts: List[Tuple[int, int, int, int]] = []
    for expert_id, row in enumerate(inbound):
        vals = sorted((int(v) for v in row), reverse=True)
        best = int(vals[0]) if len(vals) > 0 else 0
        second = int(vals[1]) if len(vals) > 1 else 0
        total = int(sum(vals))
        ranked_experts.append((-total, -(best - second), -best, int(expert_id)))
    ranked_experts.sort()
    assignment = [-1] * int(cfg.experts)
    for _, _, _, expert_id in ranked_experts:
        order = _sorted_sparks_by_inbound(inbound[int(expert_id)])
        chosen = -1
        for spark in order:
            if capacities[int(spark)] > 0:
                chosen = int(spark)
                break
        if chosen < 0:
            for spark, cap in enumerate(capacities):
                if int(cap) > 0:
                    chosen = int(spark)
                    break
        if chosen < 0:
            raise ValueError("internal error: no spark capacity left")
        assignment[int(expert_id)] = int(chosen)
        capacities[int(chosen)] -= 1
    return(assignment)


def build_affinity_spark_tables(
    layers: Sequence[Sequence[Sequence[int]]],
    cfg: ExpertTransitionProbeConfig,
) -> List[List[int]]:
    _validate_config(cfg)
    _validate_layers(layers, cfg)
    tables: List[List[int]] = [build_mod_lane_spark_table(cfg)]
    for layer_index in range(len(layers) - 1):
        inbound = [[0 for _ in range(int(cfg.sparks))] for _ in range(int(cfg.experts))]
        current_table = tables[int(layer_index)]
        cur_rows = layers[int(layer_index)]
        next_rows = layers[int(layer_index) + 1]
        for row_index in range(len(cur_rows)):
            cur_row = cur_rows[int(row_index)]
            next_row = next_rows[int(row_index)]
            for cur in cur_row:
                if int(cur) < 0 or int(cur) >= int(cfg.experts):
                    continue
                cur_spark = int(current_table[int(cur)])
                for nxt in next_row:
                    if int(nxt) < 0 or int(nxt) >= int(cfg.experts):
                        continue
                    inbound[int(nxt)][int(cur_spark)] += 1
        tables.append(_assign_next_layer_by_inbound(inbound, cfg))
    return(tables)


def _entropy_bits(counts: Sequence[int]) -> float:
    total = int(sum(int(c) for c in counts))
    if total <= 0:
        return(0.0)
    ent = 0.0
    for count in counts:
        if int(count) <= 0:
            continue
        p = float(count) / float(total)
        ent -= p * math.log2(p)
    return(float(ent))


def _conditional_metrics_for_counts(
    counts_by_current: Sequence[Sequence[int]],
    cfg: ExpertTransitionProbeConfig,
) -> Dict[str, Any]:
    top_masses = sorted(set(min(int(n), int(cfg.experts)) for n in cfg.top_masses))
    weighted: Dict[str, float] = {f"weighted_top{int(n)}_mass": 0.0 for n in top_masses}
    unweighted_values: Dict[str, List[float]] = {f"mean_top{int(n)}_mass": [] for n in top_masses}
    total_transitions = 0
    entropy_weighted = 0.0
    norm_entropy_weighted = 0.0
    active_current = 0
    top_current: List[Dict[str, Any]] = []
    log_denom = math.log2(float(cfg.experts)) if int(cfg.experts) > 1 else 1.0
    for cur, row in enumerate(counts_by_current):
        total = int(sum(int(c) for c in row))
        if total <= 0:
            continue
        active_current += 1
        total_transitions += int(total)
        ordered_counts = sorted((int(c) for c in row), reverse=True)
        masses: Dict[str, float] = {}
        for n in top_masses:
            mass = float(sum(ordered_counts[: int(n)])) / float(total)
            masses[f"top{int(n)}_mass"] = float(mass)
            weighted[f"weighted_top{int(n)}_mass"] += float(mass) * float(total)
            unweighted_values[f"mean_top{int(n)}_mass"].append(float(mass))
        entropy = _entropy_bits(row)
        norm_entropy = float(entropy) / float(log_denom) if float(log_denom) > 0.0 else 0.0
        entropy_weighted += float(entropy) * float(total)
        norm_entropy_weighted += float(norm_entropy) * float(total)
        top_next_pairs = sorted(((int(c), int(e)) for e, c in enumerate(row) if int(c) > 0), reverse=True)
        top_current.append(
            {
                "current_expert": int(cur),
                "transitions": int(total),
                "unique_next_experts": int(len(top_next_pairs)),
                "entropy_bits": float(entropy),
                "normalized_entropy": float(norm_entropy),
                **masses,
                "top_next_experts": [
                    {"expert": int(e), "count": int(c), "prob": float(c) / float(total)}
                    for c, e in top_next_pairs[: int(cfg.top_next)]
                ],
            }
        )
    summary: Dict[str, Any] = {
        "active_current_experts": int(active_current),
        "total_pair_transitions": int(total_transitions),
        "weighted_entropy_bits": 0.0,
        "weighted_normalized_entropy": 0.0,
    }
    if total_transitions > 0:
        summary["weighted_entropy_bits"] = float(entropy_weighted) / float(total_transitions)
        summary["weighted_normalized_entropy"] = float(norm_entropy_weighted) / float(total_transitions)
        for key in list(weighted.keys()):
            summary[key] = float(weighted[key]) / float(total_transitions)
    else:
        for key in list(weighted.keys()):
            summary[key] = 0.0
    for key, vals in unweighted_values.items():
        summary[key] = float(sum(vals) / float(len(vals))) if len(vals) != 0 else 0.0
    top_current.sort(key=lambda x: (-int(x["transitions"]), -float(x.get("top1_mass", 0.0)), int(x["current_expert"])))
    return({"summary": summary, "top_current_experts": top_current[: max(1, int(cfg.top_next))]})


def _count_layer_pair_transitions(
    cur_rows: Sequence[Sequence[int]],
    next_rows: Sequence[Sequence[int]],
    cfg: ExpertTransitionProbeConfig,
) -> List[List[int]]:
    counts = [[0 for _ in range(int(cfg.experts))] for _ in range(int(cfg.experts))]
    for row_index in range(len(cur_rows)):
        cur_row = cur_rows[int(row_index)]
        next_row = next_rows[int(row_index)]
        for cur in cur_row:
            if int(cur) < 0 or int(cur) >= int(cfg.experts):
                continue
            for nxt in next_row:
                if int(nxt) < 0 or int(nxt) >= int(cfg.experts):
                    continue
                counts[int(cur)][int(nxt)] += 1
    return(counts)


def _same_spark_rate(
    counts: Sequence[Sequence[int]],
    cur_table: Sequence[int],
    next_table: Sequence[int],
) -> Tuple[int, int, float]:
    total = 0
    same = 0
    for cur, row in enumerate(counts):
        cur_spark = int(cur_table[int(cur)])
        for nxt, count in enumerate(row):
            if int(count) <= 0:
                continue
            total += int(count)
            if int(next_table[int(nxt)]) == int(cur_spark):
                same += int(count)
    rate = float(same) / float(total) if int(total) > 0 else 0.0
    return(int(same), int(total), float(rate))


def analyze_expert_transitions(
    layers: Sequence[Sequence[Sequence[int]]],
    cfg: ExpertTransitionProbeConfig,
) -> Dict[str, Any]:
    _validate_config(cfg)
    tokens_per_layer, invalid = _validate_layers(layers, cfg)
    mod_table = build_mod_lane_spark_table(cfg)
    mod_tables = [list(mod_table) for _ in range(len(layers))]
    affinity_tables = build_affinity_spark_tables(layers, cfg)
    global_counts = [[0 for _ in range(int(cfg.experts))] for _ in range(int(cfg.experts))]
    layer_pairs: List[Dict[str, Any]] = []
    mod_same_total = 0
    affinity_same_total = 0
    pair_total = 0
    mod_rates: List[float] = []
    affinity_rates: List[float] = []
    reductions: List[float] = []
    for layer_index in range(len(layers) - 1):
        counts = _count_layer_pair_transitions(layers[int(layer_index)], layers[int(layer_index) + 1], cfg)
        for cur in range(int(cfg.experts)):
            grow = global_counts[int(cur)]
            row = counts[int(cur)]
            for nxt in range(int(cfg.experts)):
                grow[int(nxt)] += int(row[int(nxt)])
        mod_same, mod_total, mod_rate = _same_spark_rate(counts, mod_tables[int(layer_index)], mod_tables[int(layer_index) + 1])
        aff_same, aff_total, aff_rate = _same_spark_rate(counts, affinity_tables[int(layer_index)], affinity_tables[int(layer_index) + 1])
        if int(mod_total) != int(aff_total):
            raise ValueError("internal error: transition totals differ between maps")
        cross_mod = 1.0 - float(mod_rate)
        cross_aff = 1.0 - float(aff_rate)
        reduction = ((cross_mod - cross_aff) / cross_mod) if float(cross_mod) > 0.0 else 0.0
        mod_same_total += int(mod_same)
        affinity_same_total += int(aff_same)
        pair_total += int(mod_total)
        mod_rates.append(float(mod_rate))
        affinity_rates.append(float(aff_rate))
        reductions.append(float(reduction))
        cond = _conditional_metrics_for_counts(counts, cfg)
        layer_pairs.append(
            {
                "layer": int(layer_index),
                "next_layer": int(layer_index) + 1,
                "pair_transitions": int(mod_total),
                "mod_lane_same_spark_rate": float(mod_rate),
                "affinity_same_spark_rate": float(aff_rate),
                "affinity_cross_spark_reduction": float(reduction),
                "conditional_summary": cond["summary"],
            }
        )
    same_mod = float(mod_same_total) / float(pair_total) if int(pair_total) > 0 else 0.0
    same_aff = float(affinity_same_total) / float(pair_total) if int(pair_total) > 0 else 0.0
    cross_mod_total = 1.0 - float(same_mod)
    cross_aff_total = 1.0 - float(same_aff)
    cross_reduction = ((cross_mod_total - cross_aff_total) / cross_mod_total) if float(cross_mod_total) > 0.0 else 0.0
    conditional = _conditional_metrics_for_counts(global_counts, cfg)
    return(
        {
            "schema": "ds4_expert_transition_probe_v1",
            "tokens_per_layer": int(tokens_per_layer),
            "num_layers": int(len(layers)),
            "layer_pairs": int(len(layers) - 1),
            "experts": int(cfg.experts),
            "topk": int(cfg.topk),
            "logical_lanes": int(cfg.logical_lanes),
            "sparks": int(cfg.sparks),
            "invalid_expert_ids": int(invalid),
            "pair_transitions": int(pair_total),
            "conditional": conditional,
            "same_spark": {
                "mod_lane_same_spark_rate": float(same_mod),
                "affinity_same_spark_rate": float(same_aff),
                "affinity_cross_spark_reduction": float(cross_reduction),
                "mod_lane_same_spark_transitions": int(mod_same_total),
                "affinity_same_spark_transitions": int(affinity_same_total),
                "total_pair_transitions": int(pair_total),
            },
            "layer_pair_summary": {
                "mod_lane_same_spark_rate": _summary(mod_rates),
                "affinity_same_spark_rate": _summary(affinity_rates),
                "affinity_cross_spark_reduction": _summary(reductions),
            },
            "layer_pairs_detail": layer_pairs,
            "mod_lane_spark_table": mod_table,
            "affinity_spark_tables": affinity_tables,
        }
    )


def as_compact_report(result: Dict[str, Any], top_current: int = 8) -> Dict[str, Any]:
    conditional = result.get("conditional")
    if not isinstance(conditional, dict):
        conditional = {}
    top_rows = conditional.get("top_current_experts")
    if not isinstance(top_rows, list):
        top_rows = []
    return(
        {
            "schema": result.get("schema"),
            "tokens_per_layer": result.get("tokens_per_layer"),
            "num_layers": result.get("num_layers"),
            "layer_pairs": result.get("layer_pairs"),
            "experts": result.get("experts"),
            "topk": result.get("topk"),
            "logical_lanes": result.get("logical_lanes"),
            "sparks": result.get("sparks"),
            "invalid_expert_ids": result.get("invalid_expert_ids"),
            "pair_transitions": result.get("pair_transitions"),
            "conditional_summary": conditional.get("summary", {}),
            "same_spark": result.get("same_spark", {}),
            "layer_pair_summary": result.get("layer_pair_summary", {}),
            "top_current_experts": top_rows[: max(1, int(top_current))],
        }
    )
