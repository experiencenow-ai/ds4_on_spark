#!/usr/bin/env python3
"""Join judge-ELO quality scores onto baseline runtime CSV rows (offline).

This script does not call any paid API. It attaches `quality_score` (0..100)
derived purely from judge pairwise results (no speed fields) so the baseline
runtime loop can compute quality-adjusted tok/s via scripts/model_quality_speed_score.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


MODEL_FIELD_CANDIDATES = ("model", "model_id", "target")


def _is_finite(v: float) -> bool:
    return not (math.isnan(v) or math.isinf(v))


def _read_quality_map(path: str) -> Tuple[Dict[str, float], str]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("quality_map must be a JSON object mapping model->score")
    out: Dict[str, float] = {}
    for k, v in obj.items():
        if not isinstance(k, str) or k.strip() == "":
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if not _is_finite(fv) or fv < 0.0 or fv > 100.0:
            continue
        out[k] = fv
    return out, "judge_elo_quality_map_v1"

def _read_bundle_quality_map(path: str) -> Tuple[Dict[str, float], str]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("bundle must be a JSON object")
    qmap_obj = obj.get("quality_map")
    if not isinstance(qmap_obj, dict):
        raise ValueError("bundle.quality_map must be a JSON object mapping model->score")
    out: Dict[str, float] = {}
    for k, v in qmap_obj.items():
        if not isinstance(k, str) or k.strip() == "":
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if not _is_finite(fv) or fv < 0.0 or fv > 100.0:
            continue
        out[k] = fv
    qsrc = "judge_elo_quality_map_v1"
    meta = obj.get("meta")
    if isinstance(meta, dict):
        msrc = meta.get("quality_source")
        if isinstance(msrc, str) and msrc.strip() != "":
            qsrc = msrc.strip()
    return out, qsrc


def _read_meta_quality_source(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        return ""
    v = obj.get("quality_source")
    if isinstance(v, str) and v.strip() != "":
        return v.strip()
    return ""


def _pick_model_field(fieldnames: Sequence[str], explicit: str) -> str:
    if explicit != "":
        if explicit not in fieldnames:
            raise ValueError(f"--model-field {explicit!r} not present in CSV header")
        return explicit
    for cand in MODEL_FIELD_CANDIDATES:
        if cand in fieldnames:
            return cand
    raise ValueError(f"could not find a model field in CSV header; tried {MODEL_FIELD_CANDIDATES}")


def join_quality_rows(
    rows: Iterable[Dict[str, str]],
    quality_map: Dict[str, float],
    quality_source: str,
    model_field: str,
    overwrite: bool,
    require_all: bool,
) -> Tuple[List[Dict[str, str]], int]:
    out: List[Dict[str, str]] = []
    missing = 0
    for row in rows:
        model = row.get(model_field, "").strip()
        score = quality_map.get(model)
        existing = row.get("quality_score", "").strip()
        if score is None:
            missing += 1
            out.append(dict(row))
            continue
        if existing != "" and not overwrite:
            out.append(dict(row))
            continue
        r2 = dict(row)
        r2["quality_score"] = f"{float(score):.3f}"
        if "quality_source" not in r2 or overwrite:
            r2["quality_source"] = str(quality_source)
        out.append(r2)
    if require_all and missing != 0:
        raise ValueError(f"quality_map missing {missing} model(s) from input CSV")
    return out, missing


def _read_csv(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    with open(path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if r.fieldnames is None:
            raise ValueError("CSV must have a header row")
        rows = [dict(row) for row in r]
        return rows, list(r.fieldnames)


def _write_csv(path: str, rows: Sequence[Dict[str, str]], fieldnames: Sequence[str]) -> None:
    out_fields = list(fieldnames)
    for extra in ("quality_score", "quality_source"):
        if extra not in out_fields:
            out_fields.append(extra)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in out_fields})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="input_csv", required=True, help="baseline CSV input")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--quality-map", help="quality_map.json from scripts/judge_elo_update.py")
    src.add_argument("--bundle", help="bundle.json from scripts/judge_elo_update.py (reads quality_map + meta.quality_source)")
    ap.add_argument("--meta", default="", help="meta.json from scripts/judge_elo_update.py (optional; provides quality_source; ignored with --bundle)")
    ap.add_argument("--out", required=True, help="output CSV with quality_score attached")
    ap.add_argument("--model-field", default="", help="CSV column name for model id (default: auto-detect)")
    ap.add_argument("--overwrite", action="store_true", help="overwrite existing quality_score/quality_source if present")
    ap.add_argument("--require-all", action="store_true", help="fail if any input rows are missing from quality_map")
    ap.add_argument("--quality-source", default="", help="override quality_source value written to CSV")
    args = ap.parse_args()

    if str(getattr(args, "bundle", "") or "").strip() != "":
        qmap, qsrc = _read_bundle_quality_map(str(args.bundle))
    else:
        qmap, qsrc = _read_quality_map(str(args.quality_map))
        if str(args.meta).strip() != "":
            meta_src = _read_meta_quality_source(str(args.meta))
            if meta_src != "":
                qsrc = meta_src
    if str(args.quality_source).strip() != "":
        qsrc = str(args.quality_source).strip()
    rows, fieldnames = _read_csv(str(args.input_csv))
    model_field = _pick_model_field(fieldnames, str(args.model_field).strip())
    joined, missing = join_quality_rows(
        rows=rows,
        quality_map=qmap,
        quality_source=qsrc,
        model_field=model_field,
        overwrite=bool(args.overwrite),
        require_all=bool(args.require_all),
    )
    _write_csv(str(args.out), joined, fieldnames)
    if missing != 0:
        print(f"missing_models={missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
