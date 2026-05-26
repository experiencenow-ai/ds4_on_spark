#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARENT = Path("/private/tmp/ds4_xhigh_workspaces")
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


class WorkspaceError(Exception):
    pass


def _run(root: Path, args: list[str], capture: bool = True) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise WorkspaceError(f"git {' '.join(args)} failed: {detail}") from exc
    return (proc.stdout or "").strip()


def _workspace_path(args: argparse.Namespace) -> Path:
    if args.path:
        return Path(args.path).resolve()
    if not SAFE_NAME.match(args.name):
        raise WorkspaceError("--name must contain only letters, digits, '.', '_', or '-'")
    return (Path(args.parent).resolve() / args.name).resolve()


def _git_top(path: Path) -> Path:
    return Path(_run(path, ["rev-parse", "--show-toplevel"])).resolve()


def _status(path: Path) -> str:
    return _run(path, ["status", "--porcelain"])


def _ensure_existing_workspace(path: Path, branch: str | None) -> None:
    try:
        top = _git_top(path)
    except WorkspaceError as exc:
        raise WorkspaceError(f"{path} exists but is not a git worktree") from exc
    if top != path:
        raise WorkspaceError(f"{path} resolves to nested git root {top}")
    dirty = _status(path)
    if dirty:
        raise WorkspaceError(f"{path} already exists but is dirty; choose another --name or clean that workspace")
    current = _run(path, ["branch", "--show-current"])
    if branch and current != branch:
        raise WorkspaceError(f"{path} is on branch '{current or 'detached'}', not requested branch '{branch}'")


def _create_workspace(source_root: Path, path: Path, base_ref: str, branch: str | None, dry_run: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["worktree", "add", str(path), base_ref]
    if branch:
        cmd = ["worktree", "add", "-b", branch, str(path), base_ref]
    else:
        cmd = ["worktree", "add", "--detach", str(path), base_ref]
    if dry_run:
        print(" ".join(["git", "-C", str(source_root), *cmd]))
        return
    _run(source_root, cmd, capture=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a clean xhigh worktree without touching the current checkout.")
    parser.add_argument("--name", default="xhigh")
    parser.add_argument("--parent", default=str(DEFAULT_PARENT))
    parser.add_argument("--path")
    parser.add_argument("--source-root", default=str(REPO_ROOT))
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--branch")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        source_root = Path(args.source_root).resolve()
        path = _workspace_path(args)
        if args.fetch:
            _run(source_root, ["fetch", "origin"], capture=False)
        if path.exists():
            _ensure_existing_workspace(path, args.branch)
            print(f"clean_existing_worktree={path}")
            return 0
        _create_workspace(source_root, path, args.base_ref, args.branch, args.dry_run)
        if not args.dry_run:
            print(f"created_clean_worktree={path}")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
