#!/usr/bin/env python3
"""Summarize antirez DS4 CUDA MoE profile and runtime logs."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path


PROFILE_RE = re.compile(
    r"tokens=(?P<tokens>\d+) "
    r"pairs=(?P<pairs>\d+) "
    r"xq=(?P<xq>[0-9.]+) "
    r"sort=(?P<sort>[0-9.]+) "
    r"gateup=(?P<gateup>[0-9.]+) "
    r"midq=(?P<midq>[0-9.]+) "
    r"down=(?P<down>[0-9.]+) "
    r"sum=(?P<sum>[0-9.]+) "
    r"total=(?P<total>[0-9.]+) ms"
)

EXPERT_SLICE_RE = re.compile(
    r"CUDA MoE expert slice cache prepared "
    r"(?P<experts>\d+) selected experts "
    r"\((?P<mib>[0-9.]+) MiB\)"
)
STARTUP_STOP_RE = re.compile(
    r"accelerator stopped startup model cache after "
    r"(?P<gib>[0-9.]+) GiB at tensor span (?P<span>\d+)"
)
STARTUP_READY_RE = re.compile(
    r"CUDA startup model cache prepared "
    r"(?P<gib>[0-9.]+) GiB .* in (?P<seconds>[0-9.]+)s"
)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    return statistics.median(values)


def parse_log(path: Path) -> list[dict[str, float]]:
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = PROFILE_RE.search(line)
        if match is None:
            continue
        rec: dict[str, float] = {
            "tokens": float(match.group("tokens")),
            "pairs": float(match.group("pairs")),
        }
        for key in ("xq", "sort", "gateup", "midq", "down", "sum", "total"):
            rec[key] = float(match.group(key))
        records.append(rec)
    return records


def summarize_records(records: list[dict[str, float]]) -> list[dict[str, float | int]]:
    result: list[dict[str, float | int]] = []
    by_tokens = sorted({int(rec["tokens"]) for rec in records})
    for tokens in by_tokens:
        subset = [rec for rec in records if int(rec["tokens"]) == tokens]
        result.append({
            "tokens": tokens,
            "records": len(subset),
            "total_ms_median": median([rec["total"] for rec in subset]),
            "gateup_ms_median": median([rec["gateup"] for rec in subset]),
            "down_ms_median": median([rec["down"] for rec in subset]),
            "sort_ms_median": median([rec["sort"] for rec in subset]),
            "midq_ms_median": median([rec["midq"] for rec in subset]),
            "sum_ms_median": median([rec["sum"] for rec in subset]),
        })
    return result


def analyze_runtime_text(text: str) -> dict[str, object]:
    lines = text.splitlines()
    expert_slice_events: list[dict[str, float | int]] = []
    startup_stop_events: list[dict[str, float | int]] = []
    startup_ready_events: list[dict[str, float]] = []
    for line in lines:
        match = EXPERT_SLICE_RE.search(line)
        if match is not None:
            expert_slice_events.append({
                "experts": int(match.group("experts")),
                "mib": float(match.group("mib")),
            })
        match = STARTUP_STOP_RE.search(line)
        if match is not None:
            startup_stop_events.append({
                "gib": float(match.group("gib")),
                "tensor_span": int(match.group("span")),
            })
        match = STARTUP_READY_RE.search(line)
        if match is not None:
            startup_ready_events.append({
                "gib": float(match.group("gib")),
                "seconds": float(match.group("seconds")),
            })
    launch_timeout_count = text.count("the launch timed out and was terminated")
    illegal_memory_count = text.count("an illegal memory access was encountered")
    tensor_alloc_failed_count = text.count("CUDA tensor alloc failed")
    range_alloc_failed_count = text.count("CUDA model range alloc failed")
    recommendations: list[str] = []
    if launch_timeout_count > 0:
        recommendations.append("startup_or_kernel_timeout: shrink DS4_CUDA_MODEL_COPY_CHUNK_MB, prefer best-effort caching, and test from a non-desktop GPU session if possible")
    if illegal_memory_count > 0:
        recommendations.append("illegal_memory_access: discard the current CUDA context before trusting follow-up timings")
    if range_alloc_failed_count > 0 and len(expert_slice_events) == 0:
        recommendations.append("whole_slab_allocation_seen: enable or verify the expert-slice cache path before decode benchmarking")
    if len(expert_slice_events) == 0 and (launch_timeout_count > 0 or tensor_alloc_failed_count > 0 or range_alloc_failed_count > 0):
        recommendations.append("no_expert_slice_event: decode did not reach the selected-expert cache path or verbose logging was disabled")
    return {
        "launch_timeout_count": launch_timeout_count,
        "illegal_memory_count": illegal_memory_count,
        "tensor_alloc_failed_count": tensor_alloc_failed_count,
        "range_alloc_failed_count": range_alloc_failed_count,
        "expert_slice_events": expert_slice_events,
        "startup_stop_events": startup_stop_events,
        "startup_ready_events": startup_ready_events,
        "recommendations": recommendations,
    }


def analyze_file(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8", errors="replace")
    records = []
    for line in text.splitlines():
        match = PROFILE_RE.search(line)
        if match is None:
            continue
        rec: dict[str, float] = {
            "tokens": float(match.group("tokens")),
            "pairs": float(match.group("pairs")),
        }
        for key in ("xq", "sort", "gateup", "midq", "down", "sum", "total"):
            rec[key] = float(match.group(key))
        records.append(rec)
    runtime = analyze_runtime_text(text)
    runtime["profile_count"] = len(records)
    return {
        "path": str(path),
        "profiles": summarize_records(records),
        "runtime": runtime,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Write runtime diagnostics and profile summaries as JSON.")
    parser.add_argument("logs", nargs="+")
    args = parser.parse_args()
    if args.json:
        payload = {"logs": [analyze_file(Path(item)) for item in args.logs]}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print("log,tokens,records,total_ms,gateup_ms,down_ms,sort_ms,midq_ms,sum_ms")
    for item in args.logs:
        path = Path(item)
        records = parse_log(path)
        for summary in summarize_records(records):
            print(
                f"{path.name},{summary['tokens']},{summary['records']},"
                f"{summary['total_ms_median']:.3f},"
                f"{summary['gateup_ms_median']:.3f},"
                f"{summary['down_ms_median']:.3f},"
                f"{summary['sort_ms_median']:.3f},"
                f"{summary['midq_ms_median']:.3f},"
                f"{summary['sum_ms_median']:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
