#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
CENTAUR_REPO = Path(os.environ.get("CENTAUR_REPO", "../centaur")).resolve()
if str(CENTAUR_REPO) not in sys.path:
    sys.path.insert(0, str(CENTAUR_REPO))

from centaur_complexity import build_complexity_profile
from centaur_complexity import compact_complexity_scan
from centaur_complexity import scan_complexity


FORMAT = "ds4-repo-centaur-complexity-v1"
DEFAULT_BASELINE = ".complexity-baseline.json"
DEFAULT_INCLUDE_PATTERNS = [
    "v2/src/**",
    "v2/tests/**",
    "v2/docs/**",
    "v2/scripts/**",
    "v2/tools/**",
    "fixtures/model_contract/**",
    ".github/**",
    "README.md",
    "AGENTS.md",
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
    scan = scan_complexity(root, limit=limit, full=full, product_scope=product_scope, include_patterns=DEFAULT_INCLUDE_PATTERNS)
    return {
        "format": FORMAT,
        "status": "success",
        "profile_id": scan.get("profile_id"),
        "profile_source": "centaur_complexity",
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
        checks.append({"name": name, "current": current_value, "baseline": baseline_value, "delta": delta, "max_growth": 0.0, "ok": delta <= 0.0})
    violations = [item for item in checks if not item["ok"]]
    return {
        "format": FORMAT,
        "status": "success",
        "mode": "gate",
        "profile_id": current_scan.get("profile_id"),
        "direction": "lower_is_better",
        "gate_satisfied": len(violations) == 0,
        "decision": "accept" if not violations else "reject",
        "reason": "ok" if not violations else "complexity_regression",
        "checks": checks,
        "violation_count": len(violations),
        "violations": violations,
        "current": _gate_summary(current_scan),
        "baseline": _gate_summary(baseline_scan),
    }


def _gate_summary(scan: dict[str, Any]) -> dict[str, Any]:
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


def _write(record: dict[str, Any], output: str | None) -> None:
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Centaur complexity scoring against ds4_on_spark.")
    parser.add_argument("mode", choices=("scan", "gate", "record-baseline"))
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--product-scope", default="ignore_aware")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        current = _build_scan(root, args.limit, args.full, args.product_scope)
        if args.mode == "scan":
            _write(current, args.output)
            return 0
        if args.mode == "record-baseline":
            baseline = root / args.baseline
            baseline.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            current["baseline_path"] = str(baseline)
            _write(current, args.output)
            return 0
        gate = _build_gate(current, _load_json(root / args.baseline))
        _write(gate, args.output)
        return 0 if gate["gate_satisfied"] else 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
