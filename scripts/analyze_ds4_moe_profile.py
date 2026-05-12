#!/usr/bin/env python3
"""Summarize antirez DS4 CUDA MoE profile logs."""

from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+")
    args = parser.parse_args()
    print("log,tokens,records,total_ms,gateup_ms,down_ms,sort_ms,midq_ms,sum_ms")
    for item in args.logs:
        path = Path(item)
        records = parse_log(path)
        by_tokens = sorted({int(rec["tokens"]) for rec in records})
        for tokens in by_tokens:
            subset = [rec for rec in records if int(rec["tokens"]) == tokens]
            print(
                f"{path.name},{tokens},{len(subset)},"
                f"{median([rec['total'] for rec in subset]):.3f},"
                f"{median([rec['gateup'] for rec in subset]):.3f},"
                f"{median([rec['down'] for rec in subset]):.3f},"
                f"{median([rec['sort'] for rec in subset]):.3f},"
                f"{median([rec['midq'] for rec in subset]):.3f},"
                f"{median([rec['sum'] for rec in subset]):.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
