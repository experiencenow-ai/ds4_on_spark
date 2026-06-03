#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from ds4_infer.baked_profiles import load_json, validate_lock, verify_repos, write_rank_files


def main() -> int:
    args = _parse_args()
    v2_dir = Path(__file__).resolve().parents[1]
    repo_dir = v2_dir.parent
    lock = load_json(Path(args.lock).expanduser())
    errors = validate_lock(lock, current_env=dict(os.environ) if args.verify_current_env else None)
    if not args.skip_repo_checks:
        errors.extend(
            verify_repos(
                lock,
                ds4_repo=_path(args.ds4_repo, repo_dir),
                vllm_repo=_path(args.vllm_repo, repo_dir) if args.vllm_repo else None,
            )
        )
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    if args.write_rank_dir:
        write_rank_files(lock, Path(args.write_rank_dir).expanduser())
    if args.print_summary:
        print(json.dumps(_summary(lock), indent=2, sort_keys=True))
    if args.print_commands:
        for command in lock["launch"]["rank_commands"]:
            print(command)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify and export a baked DS4/vLLM engine lock.")
    parser.add_argument("lock")
    parser.add_argument("--ds4-repo", default=".")
    parser.add_argument("--vllm-repo", default="")
    parser.add_argument("--skip-repo-checks", action="store_true")
    parser.add_argument("--verify-current-env", action="store_true")
    parser.add_argument("--write-rank-dir", default="")
    parser.add_argument("--print-summary", action="store_true")
    parser.add_argument("--print-commands", action="store_true")
    return parser.parse_args()


def _summary(lock: dict[str, object]) -> dict[str, object]:
    return {
        "format": lock.get("format"),
        "profile_name": lock.get("profile_name"),
        "profile_hash": lock.get("profile_hash"),
        "lock_sha256": lock.get("lock_sha256"),
        "model": lock.get("model"),
        "parallelism": lock.get("parallelism"),
        "cache_root": (lock.get("env") or {}).get("VLLM_CACHE_ROOT") if isinstance(lock.get("env"), dict) else "",
        "semantic_gate_count": len(lock.get("semantic_gates") or []),
    }


def _path(raw: str, base: Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return (base / path).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
