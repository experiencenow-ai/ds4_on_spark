from __future__ import annotations

import json
import random
import re
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


_TOPK_RE = re.compile(r"ffn_moe_topk-(\d+)_pos(\d+)\.i32$")


@dataclass(frozen=True)
class Ds4TopkDumpMeta:
    dump_dir: str
    pos: int
    topk: int
    num_layers: int
    tokens_per_layer: int


def _load_i32_rows(path: Path, topk: int) -> List[List[int]]:
    data = array("i")
    data.frombytes(path.read_bytes())
    if len(data) % int(topk) != 0:
        raise ValueError(f"{path} contains {len(data)} ints, not divisible by topk={int(topk)}")
    nrows = int(len(data) // int(topk))
    out: List[List[int]] = []
    for i in range(nrows):
        row = list(data[i * int(topk) : (i + 1) * int(topk)])
        out.append(row)
    return(out)


def _layer_key(path: Path) -> Tuple[int, int]:
    m = _TOPK_RE.search(path.name)
    if m is None:
        raise ValueError(f"cannot parse DS4 topk dump name: {path}")
    return(int(m.group(1)), int(m.group(2)))


def load_ds4_ffn_moe_topk_dump_layers(
    dump_dir: str,
    *,
    pos: int = 0,
    topk: int = 6,
) -> Tuple[Ds4TopkDumpMeta, List[List[List[int]]]]:
    root = Path(dump_dir)
    paths = sorted(root.glob("*ffn_moe_topk-*_pos*.i32"), key=_layer_key)
    if len(paths) == 0:
        raise ValueError(f"no ffn_moe_topk dumps found in {root}")

    layers_by_index: Dict[int, Path] = {}
    for path in paths:
        layer, p = _layer_key(path)
        if int(p) != int(pos):
            continue
        layers_by_index[int(layer)] = path

    if len(layers_by_index) == 0:
        raise ValueError(f"no ffn_moe_topk dumps found for pos={int(pos)} in {root}")

    layer_indices = sorted(layers_by_index.keys())
    layers: List[List[List[int]]] = []
    tokens_per_layer: Optional[int] = None
    for layer in layer_indices:
        rows = _load_i32_rows(layers_by_index[int(layer)], int(topk))
        if tokens_per_layer is None:
            tokens_per_layer = len(rows)
        elif int(tokens_per_layer) != len(rows):
            raise ValueError("ffn_moe_topk dumps must have the same row count for every layer")
        layers.append(rows)

    meta = Ds4TopkDumpMeta(
        dump_dir=str(root),
        pos=int(pos),
        topk=int(topk),
        num_layers=len(layers),
        tokens_per_layer=int(tokens_per_layer or 0),
    )
    return(meta, layers)


def build_scheduler_trace_jsonl_from_ds4_topk_dump(
    meta: Ds4TopkDumpMeta,
    layers: Sequence[Sequence[Sequence[int]]],
    *,
    out_path: str,
    num_tokens: int = 0,
    seed: int = 1,
    sample_mode: str = "sequential",
    time_mode: str = "dt_ms",
    arrival_rate_tps: float = 1000.0,
    batch_size: int = 1,
    interactive_prob: float = 0.0,
) -> None:
    if sample_mode not in ("sequential", "sample", "resample"):
        raise ValueError("sample_mode must be one of: sequential, sample, resample")
    if time_mode not in ("t_ms", "dt_ms"):
        raise ValueError("time_mode must be 't_ms' or 'dt_ms'")
    if int(batch_size) <= 0:
        raise ValueError("batch_size must be > 0")
    if float(interactive_prob) < 0.0 or float(interactive_prob) > 1.0:
        raise ValueError("interactive_prob must be in [0,1]")

    if meta.tokens_per_layer <= 0:
        raise ValueError("meta.tokens_per_layer must be > 0")

    n_out = int(num_tokens) if int(num_tokens) > 0 else int(meta.tokens_per_layer)
    rng = random.Random(int(seed))

    if sample_mode == "sequential":
        n_out = min(int(n_out), int(meta.tokens_per_layer))
        indices = list(range(int(n_out)))
    elif sample_mode == "sample":
        if int(n_out) > int(meta.tokens_per_layer):
            raise ValueError("num_tokens exceeds available rows for sample_mode=sample")
        indices = rng.sample(range(int(meta.tokens_per_layer)), int(n_out))
    else:
        indices = [rng.randrange(int(meta.tokens_per_layer)) for _ in range(int(n_out))]

    dt_ms = 0.0
    if float(arrival_rate_tps) > 0.0:
        dt_ms = 1000.0 / float(arrival_rate_tps)

    meta_rec = {
        "type": "meta",
        "meta": {
            "source_format": "ds4_ffn_moe_topk_i32",
            "dump_dir": meta.dump_dir,
            "pos": int(meta.pos),
            "topk": int(meta.topk),
            "num_layers": int(meta.num_layers),
            "tokens_per_layer": int(meta.tokens_per_layer),
            "num_tokens": int(n_out),
            "sample_mode": str(sample_mode),
            "seed": int(seed),
            "time_mode": str(time_mode),
            "arrival_rate_tps": float(arrival_rate_tps),
            "batch_size": int(batch_size),
            "interactive_prob": float(interactive_prob),
        },
    }

    out = Path(out_path)
    f = open(out, "w", encoding="utf-8") if str(out_path) != "-" else None
    try:
        handle = f if f is not None else None
        if handle is None:
            import sys

            handle = sys.stdout

        handle.write(json.dumps(meta_rec, separators=(",", ":")) + "\n")

        for out_i, src_i in enumerate(indices):
            step_i = int(out_i) // int(batch_size)
            in_step = int(out_i) % int(batch_size)
            if time_mode == "t_ms":
                t_ms = float(step_i) * float(dt_ms) * float(batch_size)
                if step_i == 0 and in_step != 0:
                    t_ms = 0.0
                time_field = {"t_ms": float(t_ms)}
            else:
                if out_i == 0:
                    delta = 0.0
                elif in_step == 0:
                    delta = float(dt_ms) * float(batch_size)
                else:
                    delta = 0.0
                time_field = {"dt_ms": float(delta)}

            cls = "interactive" if rng.random() < float(interactive_prob) else "batch"
            layers_out: List[Dict[str, object]] = []
            for layer_rows in layers:
                row = layer_rows[int(src_i)]
                layers_out.append({"candidates": list(row)})

            rec = {"cls": cls, "token_index": int(out_i), "layers": layers_out}
            rec.update(time_field)
            handle.write(json.dumps(rec, separators=(",", ":")) + "\n")
    finally:
        if f is not None:
            f.close()
