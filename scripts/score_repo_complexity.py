#!/usr/bin/env python3
"""Run Centaur's complexity metric on this repository."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from centaur.centaur_complexity import build_complexity_profile
from centaur.centaur_complexity import compact_complexity_scan
from centaur.centaur_complexity import scan_complexity


FORMAT = "ds4-repo-centaur-complexity-v1"
DEFAULT_BASELINE = ".complexity-baseline.json"
DEFAULT_INCLUDE_PATTERNS = [
    "scripts/**",
    "tests/**",
    "fixtures/**",
    "centaur/**",
    ".github/**",
    "docs/CENTAUR_DASHBOARD.md",
    "docs/CENTAUR_SPECIFICATION.md",
]
GATED_METRICS = (
    "score",
    "max_function_lines",
    "functions_over_50",
    "functions_over_100",
    "repeated_normalized_blocks",
    "max_file_lines",
    "max_file_function_count",
)


class RepoComplexityError(Exception):
    pass


def _repo_root() -> Path:
    return REPO_ROOT


def _json_dump(record: dict[str, Any]) -> None:
    print(json.dumps(record, indent=2, sort_keys=True))


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepoComplexityError(f"missing complexity baseline: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RepoComplexityError(f"invalid complexity baseline JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RepoComplexityError(f"complexity baseline must be a JSON object: {path}")
    return data


def _metric_value(record: dict[str, Any], key: str) -> float:
    value = record.get(key)
    if not isinstance(value, (int, float)):
        raise RepoComplexityError(f"missing numeric complexity metric: {key}")
    return float(value)


def _build_scan(root: Path, limit: int, full: bool, product_scope: str) -> dict[str, Any]:
    profile = build_complexity_profile()
    scan = scan_complexity(
        root,
        limit=limit,
        full=full,
        product_scope=product_scope,
        include_patterns=DEFAULT_INCLUDE_PATTERNS,
    )
    return {
        "format": FORMAT,
        "status": "success",
        "profile_id": scan.get("profile_id"),
        "profile_source": "centaur.centaur_complexity",
        "profile_direction": profile.get("direction"),
        "root": str(root),
        "include_patterns": DEFAULT_INCLUDE_PATTERNS,
        "scan": compact_complexity_scan(scan),
    }


def _build_gate(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    current_scan = current.get("scan") if isinstance(current.get("scan"), dict) else current
    baseline_scan = baseline.get("scan") if isinstance(baseline.get("scan"), dict) else baseline
    if not isinstance(current_scan, dict) or not isinstance(baseline_scan, dict):
        raise RepoComplexityError("complexity gate requires current and baseline scan objects")
    checks = []
    for name in GATED_METRICS:
        current_value = _metric_value(current_scan, name)
        baseline_value = _metric_value(baseline_scan, name)
        delta = round(current_value - baseline_value, 6)
        checks.append({
            "name": name,
            "current": current_value,
            "baseline": baseline_value,
            "delta": delta,
            "max_growth": 0.0,
            "ok": delta <= 0.0,
        })
    violations = [item for item in checks if not bool(item.get("ok"))]
    return {
        "format": FORMAT,
        "status": "success",
        "mode": "gate",
        "profile_id": current_scan.get("profile_id"),
        "direction": "lower_is_better",
        "gate_satisfied": not violations,
        "decision": "accept" if not violations else "reject",
        "reason": "ok" if not violations else "complexity_regression",
        "checks": checks,
        "violation_count": len(violations),
        "violations": violations,
        "current": _gate_scan_summary(current_scan),
        "baseline": _gate_scan_summary(baseline_scan),
    }


def _gate_scan_summary(scan: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": scan.get("profile_id"),
        "file_count": scan.get("file_count"),
        "score": scan.get("score"),
        "components": scan.get("components", {}),
        "max_function_lines": scan.get("max_function_lines"),
        "functions_over_50": scan.get("functions_over_50"),
        "functions_over_100": scan.get("functions_over_100"),
        "repeated_normalized_blocks": scan.get("repeated_normalized_blocks"),
        "total_line_count": scan.get("total_line_count"),
        "max_file_lines": scan.get("max_file_lines"),
        "max_file_function_count": scan.get("max_file_function_count"),
        "top_files": [
            {
                "relative_path": item.get("relative_path"),
                "score": item.get("score"),
                "line_count": item.get("line_count"),
                "max_function_lines": item.get("max_function_lines"),
                "function_count": item.get("function_count"),
            }
            for item in scan.get("top_files", [])
            if isinstance(item, dict)
        ],
    }


def _write_output(record: dict[str, Any], output: str | None) -> None:
    if output:
        Path(output).write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _json_dump(record)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("scan", "gate", "record-baseline"))
    parser.add_argument("--root", default=str(_repo_root()))
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--product-scope", default="ignore_aware")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        record = _build_scan(root, args.limit, args.full, args.product_scope)
        if args.mode == "scan":
            _write_output(record, args.output)
            return 0
        if args.mode == "record-baseline":
            baseline_path = root / args.baseline
            baseline_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            record["baseline_path"] = str(baseline_path)
            _write_output(record, args.output)
            return 0
        baseline = _load_json(root / args.baseline)
        gate = _build_gate(record, baseline)
        _write_output(gate, args.output)
        return 0 if gate["gate_satisfied"] else 1
    except RepoComplexityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
