#!/usr/bin/env bash
# Apply one human-approved Centaur review queue candidate as a branch + commit.
set -euo pipefail

python3 - "$@" <<'PY'
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def safe_segment(value: str, limit: int = 80) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-")
    safe = safe.replace("..", ".")
    return (safe[:limit] or "candidate").rstrip(".-") or "candidate"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return data


def run_git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.strip()


def require_approved(candidate_dir: Path, allow_pending: bool) -> None:
    parts = set(candidate_dir.parts)
    if "approved" in parts:
        return
    if allow_pending and "pending" in parts:
        return
    raise ValueError("candidate must be under the approved queue; move it from pending/ after human review")


def relative_target_path(value: str) -> Path:
    rel = Path(value)
    if value == "" or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe target path: {value!r}")
    return rel


def branch_name(prefix: str, target_id: str, candidate_id: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    leaf = safe_segment(f"{target_id}-{candidate_id}", 96)
    return f"{prefix.rstrip('/')}/{stamp}-{leaf}"


def apply_source(original_file: Path, candidate_file: Path, target_file: Path) -> tuple[str, int]:
    original = original_file.read_text(encoding="utf-8")
    candidate = candidate_file.read_text(encoding="utf-8")
    current = target_file.read_text(encoding="utf-8")
    count = current.count(original)
    if count != 1:
        raise ValueError(f"expected exactly one original-source match in {target_file}, found {count}")
    return current.replace(original, candidate, 1), count


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply one approved Centaur candidate to a local Centaur checkout.")
    parser.add_argument("candidate_dir")
    parser.add_argument("--centaur-repo", default=str(Path.home() / "centaur"))
    parser.add_argument("--branch-prefix", default="centaur-approved")
    parser.add_argument("--allow-pending", action="store_true", help="test/development escape hatch; production should move entries to approved/")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    candidate_dir = Path(args.candidate_dir).expanduser().resolve()
    repo = Path(args.centaur_repo).expanduser().resolve()
    require_approved(candidate_dir, args.allow_pending)
    metadata = load_json(candidate_dir / "metadata.json") if (candidate_dir / "metadata.json").exists() else {}
    target = load_json(candidate_dir / "target.json")
    target_id = str(metadata.get("target_id") or target.get("target_id") or "target")
    candidate_id = str(metadata.get("candidate_id") or (candidate_dir / "candidate_id.txt").read_text(encoding="utf-8").strip())
    target_rel = relative_target_path(str(metadata.get("target_path") or target.get("path") or ""))
    target_file = repo / target_rel
    if not repo.exists():
        raise FileNotFoundError(f"Centaur repo not found: {repo}")
    if not target_file.exists():
        raise FileNotFoundError(f"target file not found: {target_file}")

    replacement, count = apply_source(candidate_dir / "original.py", candidate_dir / "candidate.py", target_file)
    branch = branch_name(args.branch_prefix, target_id, candidate_id)
    plan = {
        "format": "centaur-approved-apply-plan-v1",
        "candidate_dir": str(candidate_dir),
        "centaur_repo": str(repo),
        "target_path": str(target_rel),
        "target_id": target_id,
        "candidate_id": candidate_id,
        "branch": branch,
        "replace_count": count,
        "creates_commit": not args.dry_run,
        "creates_pr": False,
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    if not args.allow_dirty and run_git(repo, ["status", "--porcelain"]):
        raise RuntimeError("Centaur repo has uncommitted changes; use --allow-dirty only if you intend to mix them")
    run_git(repo, ["checkout", "-b", branch])
    target_file.write_text(replacement, encoding="utf-8")
    run_git(repo, ["diff", "--check", "--", str(target_rel)])
    run_git(repo, ["add", str(target_rel)])
    message = f"Apply approved Centaur diamond candidate {safe_segment(candidate_id, 48)}"
    run_git(repo, ["commit", "-m", message])
    commit = run_git(repo, ["rev-parse", "HEAD"])
    plan["commit"] = commit
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"apply_approved: {exc}", file=sys.stderr)
        raise SystemExit(1)
PY
