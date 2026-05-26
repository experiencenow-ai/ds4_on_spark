#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
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
    "v2/docs/**",
    "v2/scripts/**",
    "v2/tools/**",
    "fixtures/model_contract/**",
    ".github/**",
    "README.md",
    "AGENTS.md",
]
DEFAULT_EXCLUDE_PATTERNS = [
    ".centaur-audit/**",
]
CHECKED_METRICS = (
    "score",
    "max_function_lines",
    "functions_over_50",
    "functions_over_100",
    "repeated_normalized_blocks",
    "max_file_lines",
    "max_file_function_count",
)
SHAPE_GATED_METRICS = (
    "max_function_lines",
    "functions_over_50",
    "functions_over_100",
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
    scan = scan_complexity(
        root,
        limit=limit,
        full=full,
        product_scope=product_scope,
        include_patterns=DEFAULT_INCLUDE_PATTERNS,
        exclude_patterns=DEFAULT_EXCLUDE_PATTERNS,
    )
    return {
        "format": FORMAT,
        "status": "success",
        "profile_id": scan.get("profile_id"),
        "profile_source": "centaur_complexity",
        "profile_direction": profile.get("direction"),
        "root": str(root),
        "include_patterns": DEFAULT_INCLUDE_PATTERNS,
        "exclude_patterns": DEFAULT_EXCLUDE_PATTERNS,
        "scan": compact_complexity_scan(scan),
    }


def _build_gate(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return _build_named_gate(current, baseline, "gate", "static_baseline", None, SHAPE_GATED_METRICS)


def _build_pr_gate(current: dict[str, Any], base: dict[str, Any], base_ref: str | None, mode: str = "gate-pr") -> dict[str, Any]:
    return _build_named_gate(current, base, mode, "git_base", base_ref, SHAPE_GATED_METRICS)


def _build_named_gate(current: dict[str, Any], baseline: dict[str, Any], mode: str, baseline_kind: str, base_ref: str | None, gated_metrics: tuple[str, ...]) -> dict[str, Any]:
    current_scan = current.get("scan") if isinstance(current.get("scan"), dict) else current
    baseline_scan = baseline.get("scan") if isinstance(baseline.get("scan"), dict) else baseline
    if not isinstance(current_scan, dict) or not isinstance(baseline_scan, dict):
        raise RepoComplexityError("complexity gate requires current and baseline scan objects")
    checks = []
    for name in CHECKED_METRICS:
        current_value = _metric_value(current_scan, name)
        baseline_value = _metric_value(baseline_scan, name)
        delta = round(current_value - baseline_value, 6)
        gated = name in gated_metrics
        checks.append({"name": name, "current": current_value, "baseline": baseline_value, "delta": delta, "max_growth": 0.0 if gated else None, "gated": gated, "ok": True if not gated else delta <= 0.0})
    violations = [item for item in checks if item["gated"] and not item["ok"]]
    return {
        "format": FORMAT,
        "status": "success",
        "mode": mode,
        "profile_id": current_scan.get("profile_id"),
        "direction": "lower_is_better",
        "gate_satisfied": len(violations) == 0,
        "decision": "accept" if not violations else "reject",
        "reason": "ok" if not violations else "complexity_regression",
        "baseline_kind": baseline_kind,
        "base_ref": base_ref,
        "include_patterns": current.get("include_patterns", DEFAULT_INCLUDE_PATTERNS),
        "exclude_patterns": current.get("exclude_patterns", DEFAULT_EXCLUDE_PATTERNS),
        "cost": _cost_summary(current_scan, baseline_scan, checks),
        "checks": checks,
        "violation_count": len(violations),
        "violations": violations,
        "current": _gate_summary(current_scan),
        "baseline": _gate_summary(baseline_scan),
    }


def _delta(current: dict[str, Any], baseline: dict[str, Any], key: str) -> float:
    return round(_metric_value(current, key) - _metric_value(baseline, key), 6)


def _cost_summary(current_scan: dict[str, Any], baseline_scan: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "score_delta": _delta(current_scan, baseline_scan, "score"),
        "file_count_delta": _delta(current_scan, baseline_scan, "file_count"),
        "total_line_count_delta": _delta(current_scan, baseline_scan, "total_line_count"),
        "metric_deltas": {str(item["name"]): item["delta"] for item in checks},
        "gated_metrics": [str(item["name"]) for item in checks if item.get("gated")],
        "informational_metrics": [str(item["name"]) for item in checks if not item.get("gated")],
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


def _run(args: list[str]) -> str:
    try:
        proc = subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise RepoComplexityError(f"{' '.join(args)} failed: {detail}") from exc
    return proc.stdout.strip()


def _archive_ref(root: Path, base_ref: str) -> bytes:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "archive", "--format=tar", base_ref],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or b"").decode("utf-8", errors="replace").strip()
        raise RepoComplexityError(f"git archive {base_ref} failed: {detail}") from exc
    return proc.stdout


def _extract_archive(payload: bytes, target: Path) -> None:
    target_resolved = target.resolve()
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
        for member in archive.getmembers():
            destination = (target / member.name).resolve()
            if destination != target_resolved and target_resolved not in destination.parents:
                raise RepoComplexityError(f"unsafe archive member: {member.name}")
        archive.extractall(target)


def _scan_base_ref(root: Path, base_ref: str, limit: int, full: bool, product_scope: str) -> dict[str, Any]:
    tmp_parent = Path(tempfile.mkdtemp(prefix="ds4-complexity-base-"))
    base_root = tmp_parent / "repo"
    try:
        base_root.mkdir()
        _extract_archive(_archive_ref(root, base_ref), base_root)
        _run(["git", "-C", str(base_root), "init"])
        return _build_scan(base_root.resolve(), limit, full, product_scope)
    finally:
        shutil.rmtree(tmp_parent, ignore_errors=True)


def _write(record: dict[str, Any], output: str | None) -> None:
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text, end="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Centaur complexity scoring against ds4_on_spark.")
    parser.add_argument("mode", choices=("scan", "gate", "gate-baseline", "gate-pr", "record-baseline"))
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--base-root")
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
        if args.mode in {"gate", "gate-pr"}:
            if args.base_root:
                base_root = Path(args.base_root).resolve()
                base = _build_scan(base_root, args.limit, args.full, args.product_scope)
                base_ref = str(base_root)
            else:
                base = _scan_base_ref(root, args.base_ref, args.limit, args.full, args.product_scope)
                base_ref = args.base_ref
            gate = _build_pr_gate(current, base, base_ref, args.mode)
            _write(gate, args.output)
            return 0 if gate["gate_satisfied"] else 1
        gate = _build_gate(current, _load_json(root / args.baseline))
        _write(gate, args.output)
        return 0 if gate["gate_satisfied"] else 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
