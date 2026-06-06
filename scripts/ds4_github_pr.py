#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def _run(argv: list[str]) -> None:
    print("+ " + " ".join(argv), file=sys.stderr)
    subprocess.run(argv, check=True)


def _out(argv: list[str], *, check: bool = True) -> tuple[str, int, str]:
    proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    return proc.stdout.strip(), proc.returncode, proc.stderr.strip()


def _die(msg: str, code: int = 2) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def current_branch(*, allow_main: bool = False) -> str:
    branch, _, _ = _out(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if branch == "" or branch == "HEAD":
        _die("detached checkout; pass an explicit PR ref")
    if allow_main is False and branch in {"main", "master"}:
        _die("refusing to create a PR from main")
    return branch


def _read_body(args: argparse.Namespace) -> str:
    if getattr(args, "body_file", None) is not None:
        return Path(args.body_file).read_text(encoding="utf-8")
    return getattr(args, "body", "") or ""


def _pr_for_branch(branch: str) -> dict[str, object] | None:
    stdout, code, _ = _out(["gh", "pr", "view", branch, "--json", "number,url"], check=False)
    if code != 0:
        return None
    return json.loads(stdout)


def push_branch(branch: str, remote: str) -> None:
    _run(["git", "push", remote, f"HEAD:refs/heads/{branch}"])


def create_pr(args: argparse.Namespace) -> str:
    branch = args.head or current_branch()
    push_branch(branch, args.remote)
    existing = _pr_for_branch(branch)
    if existing is not None:
        url = str(existing["url"])
        print(url)
        return url
    if args.title is None:
        _die("--title is required when creating a new PR")
    argv = [
        "gh",
        "pr",
        "create",
        "--head",
        branch,
        "--base",
        args.base,
        "--title",
        args.title,
        "--body",
        _read_body(args),
    ]
    stdout, _, _ = _out(argv)
    print(stdout)
    return stdout


def _resolve_pr(ref: str | None) -> str:
    if ref is not None:
        return ref
    branch = current_branch(allow_main=True)
    if branch in {"main", "master"}:
        _die("pass a PR number, URL, or branch when running from main")
    pr = _pr_for_branch(branch)
    if pr is None:
        _die(f"no pull request found for {branch}")
    return str(pr["number"])


def _check_rows(ref: str) -> list[dict[str, object]]:
    stdout, code, stderr = _out(["gh", "pr", "checks", ref, "--json", "bucket,name,link"], check=False)
    if code not in {0, 8}:
        sys.stderr.write(stderr + "\n")
        raise SystemExit(code)
    if stdout == "":
        return []
    return json.loads(stdout)


def wait_checks(ref: str, *, interval: int, timeout: int, once: bool) -> int:
    deadline = time.time() + timeout
    while True:
        rows = _check_rows(ref)
        buckets = {str(row.get("bucket", "")) for row in rows}
        summary = ", ".join(f"{row.get('name')}={row.get('bucket')}" for row in rows) or "no checks"
        print(summary, file=sys.stderr)
        if buckets & {"fail", "cancel"}:
            return 1
        if "pending" not in buckets:
            return 0
        if once:
            return 8
        if time.time() >= deadline:
            _die(f"checks still pending after {timeout}s", 8)
        time.sleep(interval)


def merge_pr(args: argparse.Namespace) -> None:
    ref = _resolve_pr(args.pr)
    if not args.skip_checks:
        code = wait_checks(ref, interval=args.interval, timeout=args.timeout, once=False)
        if code != 0:
            raise SystemExit(code)
    argv = ["gh", "pr", "merge", ref, f"--{args.method}"]
    if args.delete_branch:
        argv.append("--delete-branch")
    _run(argv)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Standard DS4 GitHub PR workflow wrapper.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create", help="push current branch and create or print its PR")
    create.add_argument("--head")
    create.add_argument("--base", default="main")
    create.add_argument("--remote", default="origin")
    create.add_argument("--title")
    create.add_argument("--body", default="")
    create.add_argument("--body-file")
    checks = sub.add_parser("checks", help="wait for PR checks to pass")
    checks.add_argument("pr", nargs="?")
    checks.add_argument("--interval", type=int, default=10)
    checks.add_argument("--timeout", type=int, default=1800)
    checks.add_argument("--once", action="store_true")
    merge = sub.add_parser("merge", help="wait for checks and merge the PR")
    merge.add_argument("pr", nargs="?")
    merge.add_argument("--interval", type=int, default=10)
    merge.add_argument("--timeout", type=int, default=1800)
    merge.add_argument("--method", choices=("squash", "merge", "rebase"), default="squash")
    merge.add_argument("--delete-branch", action=argparse.BooleanOptionalAction, default=True)
    merge.add_argument("--skip-checks", action="store_true")
    ship = sub.add_parser("ship", help="push, create or reuse PR, wait for checks, then merge")
    ship.add_argument("--head")
    ship.add_argument("--base", default="main")
    ship.add_argument("--remote", default="origin")
    ship.add_argument("--title")
    ship.add_argument("--body", default="")
    ship.add_argument("--body-file")
    ship.add_argument("--interval", type=int, default=10)
    ship.add_argument("--timeout", type=int, default=1800)
    ship.add_argument("--method", choices=("squash", "merge", "rebase"), default="squash")
    ship.add_argument("--delete-branch", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    if args.cmd == "create":
        create_pr(args)
        return 0
    if args.cmd == "checks":
        return wait_checks(_resolve_pr(args.pr), interval=args.interval, timeout=args.timeout, once=args.once)
    if args.cmd == "merge":
        merge_pr(args)
        return 0
    if args.cmd == "ship":
        ref = create_pr(args)
        code = wait_checks(ref, interval=args.interval, timeout=args.timeout, once=False)
        if code != 0:
            return code
        merge_pr(argparse.Namespace(pr=ref, interval=args.interval, timeout=args.timeout, method=args.method, delete_branch=args.delete_branch, skip_checks=True))
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
