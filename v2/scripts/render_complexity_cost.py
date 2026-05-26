#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


MARKER = "<!-- ds4-complexity-cost-report -->"
LABELS = {
    "score": "Complexity score",
    "file_count": "Scanned files",
    "total_line_count": "Scanned lines",
    "max_function_lines": "Max function lines",
    "functions_over_50": "Functions over 50 lines",
    "functions_over_100": "Functions over 100 lines",
    "repeated_normalized_blocks": "Repeated normalized blocks",
    "max_file_lines": "Max file lines",
    "max_file_function_count": "Max file function count",
}


def _num(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def _delta(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    sign = "+" if value > 0 else ""
    return sign + _num(value)


def _row(name: str, current: Any, baseline: Any, delta: Any, gated: bool, ok: bool) -> str:
    scope = "gated" if gated else "info"
    result = "pass" if ok else "fail"
    return f"| {LABELS.get(name, name)} | `{_delta(delta)}` | `{_num(baseline)}` | `{_num(current)}` | {scope} | {result} |"


def _summary_rows(payload: dict[str, Any]) -> list[str]:
    current = payload.get("current", {})
    baseline = payload.get("baseline", {})
    rows = [
        _row("score", current.get("score"), baseline.get("score"), payload.get("cost", {}).get("score_delta"), False, True),
        _row("file_count", current.get("file_count"), baseline.get("file_count"), payload.get("cost", {}).get("file_count_delta"), False, True),
        _row("total_line_count", current.get("total_line_count"), baseline.get("total_line_count"), payload.get("cost", {}).get("total_line_count_delta"), False, True),
    ]
    for item in payload.get("checks", []):
        if item.get("name") != "score":
            rows.append(_row(
                str(item.get("name")),
                item.get("current"),
                item.get("baseline"),
                item.get("delta"),
                bool(item.get("gated")),
                bool(item.get("ok")),
            ))
    return rows


def render(payload: dict[str, Any]) -> str:
    decision = "accepted" if payload.get("gate_satisfied") else "rejected"
    lines = [
        MARKER,
        "## Centaur Complexity Cost",
        "",
        f"Decision: **{decision}**  ",
        f"Base: `{payload.get('base_ref') or payload.get('baseline_kind')}`  ",
        f"Profile: `{payload.get('profile_id')}`",
        "",
        "| metric | PR cost | base | current | gate | result |",
        "|---|---:|---:|---:|---|---|",
        *_summary_rows(payload),
        "",
        "Notes: `score`, scanned files/lines, and repeated-block totals are cost visibility, not blockers. Tests are excluded from scoring; the unit-test job still covers them.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a Markdown PR cost report from a Centaur complexity gate JSON file.")
    parser.add_argument("gate_json")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.gate_json).read_text(encoding="utf-8"))
    text = render(payload)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
