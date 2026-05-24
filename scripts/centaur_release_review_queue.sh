#!/usr/bin/env bash
# Materialize verified Centaur candidates into the human review queue.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}" python3 - "$@" <<'PY'
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from centaur_diamond_helpers import (
    utc_now,
    parse_time,
    safe_segment,
    load_json,
    write_json,
    extract_source_from_text as extract_source,
)


def record_dir_for(verified_dir: Path, row: dict[str, Any]) -> Path:
    raw = Path(str(row.get("record_dir", "")))
    if raw.exists():
        return raw
    candidate = verified_dir / "records" / raw.name
    if candidate.exists():
        return candidate
    safe = verified_dir / "records" / safe_segment(str(row.get("candidate_id", "")))
    if safe.exists():
        return safe
    raise FileNotFoundError(f"record dir not found for {row.get('candidate_id')!r}")


def accepted_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = summary.get("accepted")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    rows = summary.get("records", [])
    return [row for row in rows if isinstance(row, dict) and row.get("accepted_for_review")]


def target_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = summary.get("records", [])
    return [row for row in rows if isinstance(row, dict)]


def copy_one_candidate(queue_root: Path, verified_dir: Path, run_date: str, row: dict[str, Any]) -> dict[str, Any]:
    record_dir = record_dir_for(verified_dir, row)
    target = load_json(record_dir / "target.json")
    proposal = load_json(record_dir / "proposal.json")
    verification = load_json(record_dir / "verification.json")
    target_id = str(target.get("target_id") or row.get("target_id") or "target")
    candidate_id = str(proposal.get("candidate_id") or row.get("candidate_id") or "candidate")
    destination = queue_root / "pending" / safe_segment(target_id) / run_date / safe_segment(candidate_id)
    destination.mkdir(parents=True, exist_ok=True)

    original = str(target.get("source", ""))
    candidate = extract_source(str(proposal.get("text", "")))
    (destination / "original.py").write_text(original, encoding="utf-8")
    (destination / "candidate.py").write_text(candidate, encoding="utf-8")
    diff = difflib.unified_diff(
        original.splitlines(True),
        candidate.splitlines(True),
        fromfile="original.py",
        tofile="candidate.py",
    )
    (destination / "diff.patch").write_text("".join(diff), encoding="utf-8")
    shutil.copy2(record_dir / "verification.json", destination / "verification.json")
    shutil.copy2(record_dir / "target.json", destination / "target.json")
    shutil.copy2(record_dir / "proposal.json", destination / "proposal.json")
    packet = record_dir / "review_packet.md"
    if packet.exists():
        shutil.copy2(packet, destination / "review_packet.md")
    else:
        (destination / "review_packet.md").write_text(
            f"# Centaur candidate\n\n- target: `{target_id}`\n- candidate: `{candidate_id}`\n",
            encoding="utf-8",
        )
    (destination / "target_id.txt").write_text(target_id + "\n", encoding="utf-8")
    (destination / "candidate_id.txt").write_text(candidate_id + "\n", encoding="utf-8")
    metadata = {
        "format": "centaur-review-queue-entry-v1",
        "candidate_id": candidate_id,
        "target_id": target_id,
        "target_path": target.get("path", ""),
        "queued_at": utc_now().isoformat().replace("+00:00", "Z"),
        "diamond_score": verification.get("diamond_score"),
        "verification_level": verification.get("verification_level"),
        "accepted_for_review": verification.get("accepted_for_review"),
        "safe_to_auto_apply": False,
        "source_record_dir": str(record_dir),
    }
    write_json(destination / "metadata.json", metadata)
    return {"target_id": target_id, "candidate_id": candidate_id, "path": str(destination), "diamond_score": verification.get("diamond_score", 0.0)}


def model_for_record(record_dir: Path, default: str) -> str:
    proposal = record_dir / "proposal.json"
    if not proposal.exists():
        return default
    return str(load_json(proposal).get("model") or default)


def update_stats(
    queue_root: Path,
    verified_dir: Path,
    summary: dict[str, Any],
    accepted: list[dict[str, Any]],
    args: argparse.Namespace,
    started: dt.datetime,
    ended: dt.datetime,
) -> dict[str, Any]:
    stats_path = queue_root / "stats.json"
    stats = load_json(stats_path) if stats_path.exists() else {"format": "centaur-diamond-loop-stats-v1", "runs": []}
    runs = [run for run in stats.get("runs", []) if isinstance(run, dict) and run.get("run_id") != args.run_id]
    run_targets: dict[str, dict[str, float]] = {}
    run_models: dict[str, dict[str, float]] = {}
    accepted_ids = {str(row.get("candidate_id")) for row in accepted}
    score_sum = 0.0

    for row in target_rows(summary):
        target_id = str(row.get("target_id", "unknown"))
        score = float(row.get("diamond_score") or 0.0)
        accepted_row = bool(row.get("accepted_for_review")) or str(row.get("candidate_id")) in accepted_ids
        target_rec = run_targets.setdefault(target_id, {"proposals": 0, "accepted": 0, "diamond_score_sum": 0.0})
        target_rec["proposals"] += 1
        if accepted_row:
            target_rec["accepted"] += 1
            target_rec["diamond_score_sum"] += score
            score_sum += score
        try:
            record_dir = record_dir_for(verified_dir, row)
            model = model_for_record(record_dir, args.model)
        except Exception:
            model = args.model
        model_rec = run_models.setdefault(model, {"proposals": 0, "accepted": 0, "diamond_score_sum": 0.0})
        model_rec["proposals"] += 1
        if accepted_row:
            model_rec["accepted"] += 1
            model_rec["diamond_score_sum"] += score

    wall_seconds = float(args.wall_clock_seconds) if args.wall_clock_seconds is not None else max(0.0, (ended - started).total_seconds())
    run = {
        "run_id": args.run_id,
        "run_date": started.date().isoformat(),
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "ended_at": ended.isoformat().replace("+00:00", "Z"),
        "spark": args.spark,
        "model": args.model,
        "proposal_count": int(summary.get("proposal_count") or 0),
        "candidate_count": int(summary.get("candidate_count") or summary.get("proposal_count") or 0),
        "verified_count": int(summary.get("verified_count") or 0),
        "accepted_count": int(summary.get("accepted_count") or len(accepted)),
        "rejected_count": int(summary.get("rejected_count") or 0),
        "skipped_duplicate_count": int(summary.get("skipped_duplicate_count") or 0),
        "error_count": int(summary.get("error_count") or 0),
        "wall_clock_hours": round(wall_seconds / 3600.0, 6),
        "diamond_score_sum": round(score_sum, 6),
        "targets": run_targets,
        "models": run_models,
    }
    runs.append(run)

    cutoff = started - dt.timedelta(days=int(args.window_days))
    kept = []
    for item in runs:
        try:
            day = dt.date.fromisoformat(str(item.get("run_date")))
        except Exception:
            kept.append(item)
            continue
        if day >= cutoff.date():
            kept.append(item)

    stats = {
        "format": "centaur-diamond-loop-stats-v1",
        "updated_at": utc_now().isoformat().replace("+00:00", "Z"),
        "window_days": int(args.window_days),
        "runs": kept,
    }
    stats["aggregates"] = aggregate_stats(kept)
    write_json(stats_path, stats)
    return stats


def merge_counter(dst: dict[str, dict[str, float]], src: dict[str, Any]) -> None:
    for key, value in src.items():
        if not isinstance(value, dict):
            continue
        rec = dst.setdefault(key, {"proposals": 0, "accepted": 0, "diamond_score_sum": 0.0})
        rec["proposals"] += float(value.get("proposals") or 0)
        rec["accepted"] += float(value.get("accepted") or 0)
        rec["diamond_score_sum"] += float(value.get("diamond_score_sum") or 0.0)


def finalize_rates(records: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for key, rec in sorted(records.items()):
        proposals = rec.get("proposals", 0.0)
        accepted = rec.get("accepted", 0.0)
        score_sum = rec.get("diamond_score_sum", 0.0)
        out[key] = {
            "proposals": int(proposals),
            "accepted": int(accepted),
            "acceptance_rate": round((accepted / proposals) if proposals else 0.0, 6),
            "diamond_score_sum": round(score_sum, 6),
            "mean_diamond_score": round((score_sum / proposals) if proposals else 0.0, 6),
        }
    return out


def aggregate_stats(runs: list[dict[str, Any]]) -> dict[str, Any]:
    targets: dict[str, dict[str, float]] = {}
    models: dict[str, dict[str, float]] = {}
    days: dict[str, dict[str, float]] = {}
    sparks: dict[str, dict[str, float]] = {}
    for run in runs:
        merge_counter(targets, run.get("targets", {}))
        merge_counter(models, run.get("models", {}))
        day = str(run.get("run_date", "unknown"))
        day_rec = days.setdefault(day, {"candidates_produced": 0, "accepted": 0, "wall_clock_hours": 0.0, "diamond_score_sum": 0.0})
        day_rec["candidates_produced"] += float(run.get("candidate_count") or 0)
        day_rec["accepted"] += float(run.get("accepted_count") or 0)
        day_rec["wall_clock_hours"] += float(run.get("wall_clock_hours") or 0.0)
        day_rec["diamond_score_sum"] += float(run.get("diamond_score_sum") or 0.0)
        spark = str(run.get("spark", "unknown"))
        spark_rec = sparks.setdefault(spark, {"total_wall_clock_hours": 0.0, "model_load_count": 0})
        spark_rec["total_wall_clock_hours"] += float(run.get("wall_clock_hours") or 0.0)
        spark_rec["model_load_count"] += 1
    per_model = finalize_rates(models)
    best = sorted(
        (
            {
                "model": model,
                "quality": round(rec["acceptance_rate"] * rec["diamond_score_sum"], 6),
                **rec,
            }
            for model, rec in per_model.items()
        ),
        key=lambda item: item["quality"],
        reverse=True,
    )
    return {
        "per_target": finalize_rates(targets),
        "per_model": per_model,
        "per_day": {key: {k: round(v, 6) if isinstance(v, float) else int(v) for k, v in value.items()} for key, value in sorted(days.items())},
        "per_spark": {key: {"total_wall_clock_hours": round(float(value["total_wall_clock_hours"]), 6), "model_load_count": int(value["model_load_count"])} for key, value in sorted(sparks.items())},
        "best_models": best[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Release verified Centaur candidates into the review queue.")
    parser.add_argument("--verified-dir", required=True)
    parser.add_argument("--queue-root", default=str(Path.home() / "centaur_review_queue"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--spark", default="unknown")
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--started-at", default="")
    parser.add_argument("--ended-at", default="")
    parser.add_argument("--wall-clock-seconds", type=float)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    verified_dir = Path(args.verified_dir).expanduser().resolve()
    queue_root = Path(args.queue_root).expanduser().resolve()
    summary_path = verified_dir / "verification_summary.json"
    if not summary_path.exists():
        summary_path = verified_dir / "verification_index.json"
    summary = load_json(summary_path)
    accepted = accepted_rows(summary)
    started = parse_time(args.started_at)
    ended = parse_time(args.ended_at)

    if args.dry_run:
        print(json.dumps({"accepted_count": len(accepted), "queue_root": str(queue_root), "verified_dir": str(verified_dir)}, indent=2, sort_keys=True))
        return 0

    for subdir in ("pending", "approved", "rejected", "failures", "incoming", "runs"):
        (queue_root / subdir).mkdir(parents=True, exist_ok=True)
    run_copy = queue_root / "runs" / safe_segment(args.run_id)
    if not run_copy.exists():
        shutil.copytree(verified_dir, run_copy)

    queued = [copy_one_candidate(queue_root, verified_dir, started.date().isoformat(), row) for row in accepted]
    stats = update_stats(queue_root, verified_dir, summary, accepted, args, started, ended)
    print(
        json.dumps(
            {
                "format": "centaur-review-queue-release-v1",
                "queue_root": str(queue_root),
                "run_copy": str(run_copy),
                "queued_count": len(queued),
                "queued": queued,
                "stats_path": str(queue_root / "stats.json"),
                "best_models": stats.get("aggregates", {}).get("best_models", []),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
