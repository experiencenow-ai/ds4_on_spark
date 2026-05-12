from __future__ import annotations

import dataclasses
import math
import random
import statistics
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def _percentile(values: Sequence[float], q: float) -> float:
    if len(values) == 0:
        return(0.0)
    ordered = sorted(values)
    idx = int(float(q) * float(len(ordered) - 1))
    if idx < 0:
        idx = 0
    if idx >= len(ordered):
        idx = len(ordered) - 1
    return(float(ordered[idx]))


def _summary(values: Iterable[float]) -> Dict[str, float]:
    vals = list(values)
    if len(vals) == 0:
        return({"min": 0.0, "median": 0.0, "max": 0.0})
    return(
        {
            "min": float(min(vals)),
            "median": float(statistics.median(vals)),
            "max": float(max(vals)),
        }
    )


@dataclass(frozen=True)
class ExpertQueueProbeConfig:
    experts: int = 256
    topk: int = 6
    batches: Tuple[int, ...] = (16, 32, 64, 100, 128, 256, 512)
    trials: int = 250
    seed: int = 20260512
    strict_expert_ids: bool = True


@dataclass(frozen=True)
class ExpertQueueProbeResult:
    tokens_per_layer: int
    num_layers: int
    experts: int
    topk: int
    trials: int
    batches: Dict[str, Dict[str, Dict[str, float]]]
    invalid_expert_ids: int


def analyze_ds4_ffn_moe_topk_layers(
    layers: Sequence[Sequence[Sequence[int]]],
    cfg: ExpertQueueProbeConfig,
) -> ExpertQueueProbeResult:
    if int(cfg.experts) <= 0:
        raise ValueError("experts must be > 0")
    if int(cfg.topk) <= 0:
        raise ValueError("topk must be > 0")
    if int(cfg.trials) <= 0:
        raise ValueError("trials must be > 0")
    if len(cfg.batches) == 0:
        raise ValueError("batches must be non-empty")
    if len(layers) == 0:
        raise ValueError("layers must be non-empty")

    tokens_per_layer: Optional[int] = None
    for layer_rows in layers:
        if tokens_per_layer is None:
            tokens_per_layer = len(layer_rows)
        elif int(tokens_per_layer) != len(layer_rows):
            raise ValueError("each layer must have the same number of rows")
    tokens = int(tokens_per_layer or 0)
    if tokens <= 0:
        raise ValueError("tokens_per_layer must be > 0")

    rng = random.Random(int(cfg.seed))
    invalid = 0
    per_layer: List[Dict[str, object]] = []

    for layer_index, layer_rows in enumerate(layers):
        layer_out: Dict[str, object] = {"layer_index": int(layer_index), "tokens": int(tokens), "batches": {}}
        batch_out: Dict[str, object] = {}
        for batch in cfg.batches:
            if int(batch) <= 0:
                raise ValueError("batch sizes must be > 0")

            active_vals: List[float] = []
            max_vals: List[float] = []
            mean_active_vals: List[float] = []
            p90_vals: List[float] = []
            p99_vals: List[float] = []
            tiles6_vals: List[float] = []
            speed6_vals: List[float] = []
            overflow6_vals: List[float] = []

            for _ in range(int(cfg.trials)):
                if int(batch) <= tokens:
                    idxs = rng.sample(range(tokens), int(batch))
                else:
                    idxs = [rng.randrange(tokens) for _ in range(int(batch))]

                counts = [0] * int(cfg.experts)
                invalid_this = 0
                for idx in idxs:
                    row = layer_rows[int(idx)]
                    if len(row) != int(cfg.topk):
                        raise ValueError("each dump row must have exactly topk entries")
                    for expert in row:
                        if int(expert) < 0 or int(expert) >= int(cfg.experts):
                            invalid_this += 1
                            continue
                        counts[int(expert)] += 1
                if cfg.strict_expert_ids and invalid_this != 0:
                    raise ValueError("encountered out-of-range expert IDs; pass strict_expert_ids=False to ignore")
                invalid += int(invalid_this)

                nonzero = [count for count in counts if int(count) > 0]
                tiles6 = sum(int(math.ceil(float(count) / 6.0)) for count in nonzero)
                active = len(nonzero)
                total_pairs = int(batch) * int(cfg.topk)

                active_vals.append(float(active))
                max_vals.append(float(max(nonzero) if len(nonzero) != 0 else 0))
                mean_active_vals.append(float(total_pairs) / float(active) if active > 0 else 0.0)
                p90_vals.append(_percentile([float(c) for c in nonzero], 0.90))
                p99_vals.append(_percentile([float(c) for c in nonzero], 0.99))
                tiles6_vals.append(float(tiles6))
                speed6_vals.append(float(total_pairs) / float(tiles6) if tiles6 > 0 else 0.0)
                overflow6_vals.append(float(sum(max(0, int(count) - 6) for count in nonzero)))

            batch_out[str(int(batch))] = {
                "active": _summary(active_vals),
                "max_depth": _summary(max_vals),
                "mean_active_depth": _summary(mean_active_vals),
                "p90_depth": _summary(p90_vals),
                "p99_depth": _summary(p99_vals),
                "tiles6": _summary(tiles6_vals),
                "pair_speedup_cap6": _summary(speed6_vals),
                "overflow_pairs_over6": _summary(overflow6_vals),
            }

        layer_out["batches"] = batch_out
        per_layer.append(layer_out)

    summary_batches: Dict[str, Dict[str, Dict[str, float]]] = {}
    for batch in cfg.batches:
        key = str(int(batch))
        summary_batches[key] = {}
        for metric in (
            "active",
            "max_depth",
            "mean_active_depth",
            "p90_depth",
            "p99_depth",
            "tiles6",
            "pair_speedup_cap6",
            "overflow_pairs_over6",
        ):
            medians = []
            for layer in per_layer:
                layer_batches = layer.get("batches")
                if not isinstance(layer_batches, dict):
                    continue
                m = layer_batches.get(key)
                if not isinstance(m, dict):
                    continue
                metric_block = m.get(metric)
                if not isinstance(metric_block, dict):
                    continue
                med = metric_block.get("median")
                if isinstance(med, (int, float)):
                    medians.append(float(med))
            summary_batches[key][metric] = _summary(medians)

    return(
        ExpertQueueProbeResult(
            tokens_per_layer=int(tokens),
            num_layers=int(len(layers)),
            experts=int(cfg.experts),
            topk=int(cfg.topk),
            trials=int(cfg.trials),
            batches=summary_batches,
            invalid_expert_ids=int(invalid),
        )
    )

