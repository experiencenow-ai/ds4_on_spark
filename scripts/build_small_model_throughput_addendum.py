#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any


FORMAT = "small-model-throughput-addendum-v1"
SOURCE_FORMAT = "small-model-qualification-v1"


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def qualification_record_paths(paths: list[Path]) -> list[Path]:
    records: list[Path] = []
    for path in paths:
        if path.is_dir():
            records.extend(sorted(candidate for candidate in path.glob("*.json") if not candidate.name.startswith("batch_summary")))
        else:
            records.append(path)
    return sorted(records)


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def reason_cannot_derive(record: dict[str, Any]) -> str | None:
    if record.get("format") != SOURCE_FORMAT:
        return "not_small_model_qualification_record"
    if record.get("status") != "passed":
        return "record_status_not_passed"
    aggregate = record.get("aggregate_metrics") or {}
    mean_tok_s = number_or_none(aggregate.get("mean_tok_s"))
    median_tok_s = number_or_none(aggregate.get("median_tok_s"))
    if mean_tok_s is None:
        return "missing_mean_tok_s"
    if median_tok_s is None:
        return "missing_median_tok_s"
    return None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def derive_p50_latency_ms(record: dict[str, Any]) -> float | None:
    aggregate = record.get("aggregate_metrics") or {}
    aggregate_p50 = number_or_none(aggregate.get("p50_latency_ms"))
    if aggregate_p50 is not None:
        return aggregate_p50
    latencies: list[float] = []
    for result in record.get("per_prompt_results") or []:
        latency = number_or_none(result.get("latency_ms"))
        if latency is not None:
            latencies.append(latency)
    return median(latencies)


def derive_record(path: Path, root: Path) -> dict[str, Any]:
    record = load_json(path)
    aggregate = record.get("aggregate_metrics") or {}
    cost = record.get("cost_proxy_estimate") or {}
    reason = reason_cannot_derive(record)
    source_path = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    row: dict[str, Any] = {
        "model_id": record.get("model_id"),
        "source_record": source_path,
        "status": record.get("status"),
        "serve_backend": record.get("serve_backend"),
        "derivation_status": "cannot_derive" if reason is not None else "derived",
        "cannot_derive_reason": reason,
        "prompt_count": int(aggregate.get("prompt_count") or 0),
        "pass_count": int(aggregate.get("pass_count") or 0),
        "pass_rate": number_or_none(aggregate.get("pass_rate")),
        "mean_tok_s": number_or_none(aggregate.get("mean_tok_s")) if reason is None else None,
        "median_tok_s": number_or_none(aggregate.get("median_tok_s")) if reason is None else None,
        "p50_latency_ms": derive_p50_latency_ms(record) if reason is None else None,
        "p95_latency_ms": number_or_none(aggregate.get("p95_latency_ms")) if reason is None else None,
        "cost_proxy": number_or_none(cost.get("score")),
        "cost_proxy_basis": cost.get("basis"),
    }
    return row


def top_by(rows: list[dict[str, Any]], key: str, reverse: bool) -> list[dict[str, Any]]:
    eligible = [row for row in rows if row.get("derivation_status") == "derived" and row.get(key) is not None]
    return [
        {
            "model_id": row.get("model_id"),
            key: row.get(key),
            "pass_rate": row.get("pass_rate"),
            "serve_backend": row.get("serve_backend"),
            "source_record": row.get("source_record"),
        }
        for row in sorted(eligible, key=lambda item: item[key], reverse=reverse)[:10]
    ]


def build_addendum(paths: list[Path], root: Path, run_id: str | None = None) -> dict[str, Any]:
    record_paths = [path.resolve() for path in qualification_record_paths(paths)]
    rows = [derive_record(path, root) for path in record_paths]
    passed = [row for row in rows if row.get("status") == "passed"]
    derived = [row for row in passed if row.get("derivation_status") == "derived"]
    cannot = [row for row in passed if row.get("derivation_status") != "derived"]
    source_dirs = sorted({str(path.parent.relative_to(root)) if path.parent.is_relative_to(root) else str(path.parent) for path in record_paths})
    return {
        "format": FORMAT,
        "run_id": run_id or utc_now().replace(":", "").replace("-", ""),
        "created_at": utc_now(),
        "source_record_dirs": source_dirs,
        "record_count": len(rows),
        "passed_record_count": len(passed),
        "derived_passed_record_count": len(derived),
        "cannot_derive_passed_record_count": len(cannot),
        "coverage": {
            "passed_records_accounted_for": len(passed) == (len(derived) + len(cannot)),
            "passed_records_with_tok_s": len(derived),
            "passed_records_without_tok_s": len(cannot),
        },
        "top_by_mean_tok_s": top_by(rows, "mean_tok_s", True),
        "top_by_cost_proxy": top_by(rows, "cost_proxy", False),
        "records": rows,
    }


def validate_addendum(addendum: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if addendum.get("format") != FORMAT:
        errors.append("format must be small-model-throughput-addendum-v1")
    if not addendum.get("coverage", {}).get("passed_records_accounted_for"):
        errors.append("passed records are not fully accounted for")
    if int(addendum.get("derived_passed_record_count") or 0) <= 0:
        errors.append("no passed records have derived tok/s")
    if not addendum.get("top_by_mean_tok_s"):
        errors.append("top_by_mean_tok_s must be non-empty")
    if not addendum.get("top_by_cost_proxy"):
        errors.append("top_by_cost_proxy must be non-empty")
    for index, row in enumerate(addendum.get("records") or []):
        if row.get("status") == "passed" and row.get("derivation_status") == "derived":
            if number_or_none(row.get("mean_tok_s")) is None:
                errors.append(f"records[{index}] derived row missing mean_tok_s")
            if number_or_none(row.get("median_tok_s")) is None:
                errors.append(f"records[{index}] derived row missing median_tok_s")
            if number_or_none(row.get("p50_latency_ms")) is None:
                errors.append(f"records[{index}] derived row missing p50_latency_ms")
            if number_or_none(row.get("p95_latency_ms")) is None:
                errors.append(f"records[{index}] derived row missing p95_latency_ms")
        if row.get("status") == "passed" and row.get("derivation_status") == "cannot_derive":
            if not row.get("cannot_derive_reason"):
                errors.append(f"records[{index}] cannot_derive row missing reason")
    return errors


def print_summary(addendum: dict[str, Any]) -> None:
    print(json.dumps({
        "format": addendum.get("format"),
        "record_count": addendum.get("record_count"),
        "passed_record_count": addendum.get("passed_record_count"),
        "derived_passed_record_count": addendum.get("derived_passed_record_count"),
        "cannot_derive_passed_record_count": addendum.get("cannot_derive_passed_record_count"),
        "top_by_mean_tok_s": addendum.get("top_by_mean_tok_s", [])[:3],
        "top_by_cost_proxy": addendum.get("top_by_cost_proxy", [])[:3],
    }, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive small-model tok/s addenda from executed qualification records.")
    subparsers = parser.add_subparsers(dest="command")
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("paths", nargs="+")
    build_parser.add_argument("--output", required=True)
    build_parser.add_argument("--run-id", default=None)
    build_parser.add_argument("--root", default=".")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    if args.command == "build":
        root = Path(args.root).resolve()
        addendum = build_addendum([Path(path) for path in args.paths], root, args.run_id)
        errors = validate_addendum(addendum)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        write_json(Path(args.output), addendum)
        print_summary(addendum)
        return 0
    if args.command == "validate":
        had_error = False
        for path in args.paths:
            addendum = load_json(Path(path))
            errors = validate_addendum(addendum)
            if errors:
                had_error = True
                for error in errors:
                    print(f"{path}: {error}", file=sys.stderr)
            else:
                print(f"{path}: ok")
        return 1 if had_error else 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
