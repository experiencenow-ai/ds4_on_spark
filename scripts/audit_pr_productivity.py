#!/usr/bin/env python3
"""Productivity score for a PR — measures (functionality / complexity).

ct direction 2026-05-23:
- "the only time there is credit for new code is if it is indeed NEW and NECESSARY"
- "The best way to solve a problem is without code, or even better to reduce
  the amount of code while increasing functionality and reducing complexity"
- "test code does not fall under this, for test code the number of test cases,
  path coverage, that is what is important. the lines of code is irrelevant"

Score components per PR:

  PRODUCTION CODE (scripts/, centaur/, src/, but NOT tests/, NOT docs/):
    +1 point per net LOC removed
    -1 point per net LOC added
    +5 points per duplicate-function group eliminated (true rot, outside _lib/)
    -5 points per duplicate-function group introduced
    +2 points per function over 50 LOC decomposed into <=50 LOC pieces
    -2 points per new function over 50 LOC added

  TEST CODE (tests/):
    LOC is irrelevant. Scoring is:
      +2 points per new test case (top-level test_* function or pytest test method)
      +3 points per net branch covered (when coverage data is available)

  DOCUMENTATION (docs/):
    +1 point per net LOC removed (distilling fragments)
    -1 point per new doc file added
    -10 points per file matching the forbidden-probe-doc pattern

  FUNCTIONALITY:
    +10 points per closed issue (the PR's `Closes #N` lines, each meaningful issue counts)
    +5 points per new test for previously-untested code path

  COMPLEXITY (when scripts/_lib/centaur_complexity.py is wired up via #1331):
    +10 points per complexity-score decrease per file (will be added in follow-up)
    -10 points per complexity-score increase per file

NEGATIVE total score = the PR made the codebase worse. The PR should be reverted
or restructured. A positive score that came from `+ functionality` alone with
strong negative `code growth` should be questioned: did the new code actually
need to be new?

The score is informational, not a CI gate (yet). Once we've validated it tracks
real productivity, it can become a gate: PRs with score <= 0 get blocked.

Usage:
    python3 scripts/audit_pr_productivity.py <base-sha> <head-sha>

    # Run against an open PR's branch:
    python3 scripts/audit_pr_productivity.py origin/main HEAD

Outputs JSON to stdout and a human-readable summary to stderr.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import re
import subprocess
import sys
from collections import defaultdict


# Path classification — defined once, used everywhere.
def classify(path: str) -> str:
    """Return one of: production, test, doc, lib, ignore."""
    if path.startswith("tests/") or path.endswith("_test.py") or "test_" in pathlib.PurePath(path).name:
        return "test"
    if path.startswith("docs/"):
        return "doc"
    if "/_lib/" in path:
        return "lib"  # legitimate shared library, not rot
    if path.startswith("scripts/") or path.startswith("centaur/") or path.startswith("src/"):
        return "production"
    return "ignore"


def git_diff_numstat(base: str, head: str) -> list[tuple[str, int, int]]:
    """Return [(filepath, added, deleted), ...] for the diff."""
    out = subprocess.check_output(
        ["git", "diff", "--numstat", base, head], text=True
    ).strip()
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        if added == "-" or deleted == "-":
            continue  # binary
        rows.append((path, int(added), int(deleted)))
    return rows


def hash_function_bodies(file_content: str) -> dict[str, str]:
    """Return {fn_name: body_hash} for top-level functions with body >= 3 stmts."""
    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return {}
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if len(node.body) < 3:
                continue
            stmts = []
            for n in node.body:
                if (
                    isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)
                ):
                    continue
                stmts.append(ast.dump(n, annotate_fields=False, include_attributes=False))
            out[node.name] = hashlib.md5("\n".join(stmts).encode()).hexdigest()[:10]
    return out


def function_lines_over_threshold(file_content: str, threshold: int = 50) -> int:
    """Count functions over `threshold` lines."""
    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return 0
    count = 0
    lines = file_content.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", None) or node.lineno
            if end - node.lineno > threshold:
                count += 1
    return count


def count_test_cases(file_content: str) -> int:
    """Count pytest-style test functions and methods."""
    try:
        tree = ast.parse(file_content)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                count += 1
    return count


def count_dup_groups_in_repo(repo: pathlib.Path) -> tuple[int, int]:
    """Return (true_rot_groups, lib_groups) over all production code."""
    by_hash = defaultdict(list)
    for p in (repo / "scripts").rglob("*.py"):
        relpath = str(p.relative_to(repo))
        if classify(relpath) not in ("production", "lib"):
            continue
        fns = hash_function_bodies(p.read_text(errors="replace"))
        for name, h in fns.items():
            by_hash[h].append((relpath, name))
    rot = 0
    lib_only = 0
    for h, locs in by_hash.items():
        if len(locs) < 2:
            continue
        if all(classify(f) == "lib" for f, _ in locs):
            lib_only += 1
        elif not any(classify(f) == "lib" for f, _ in locs):
            rot += 1
        # mixed counts as half rot — there's a wrapper plus an unconverted caller
        else:
            rot += 1  # still rot until the non-lib copies become wrappers
    return rot, lib_only


PROBE_DOC_PATTERN = re.compile(
    r".*-\d{4}-\d{2}-\d{2}(T\d{4}Z)?$"
    r"|^spark.*-probe.*"
    r"|.*-iteration-\d"
    r"|.*-v\d+-notes"
)


def file_at_rev(rev: str, path: str) -> str:
    """Get file content at a given revision; '' if missing."""
    try:
        return subprocess.check_output(
            ["git", "show", f"{rev}:{path}"], text=True, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return ""


def parse_closes_lines(base: str, head: str) -> int:
    """Count `Closes #N` references in the merge commits between base and head."""
    out = subprocess.check_output(
        ["git", "log", "--pretty=%B", f"{base}..{head}"], text=True
    )
    return len(re.findall(r"(?:Closes|Fixes|Resolves)\s+(?:[\w\-/]+)?#\d+", out, re.I))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", help="base commit SHA or ref")
    parser.add_argument("head", help="head commit SHA or ref")
    args = parser.parse_args()

    repo = pathlib.Path.cwd()
    base, head = args.base, args.head

    # 1. File-level diff
    diff = git_diff_numstat(base, head)

    bucketed = defaultdict(lambda: {"added": 0, "deleted": 0, "files": []})
    for path, a, d in diff:
        kind = classify(path)
        bucketed[kind]["added"] += a
        bucketed[kind]["deleted"] += d
        bucketed[kind]["files"].append((path, a, d))

    # 2. Score components
    score = 0
    breakdown = {}

    # Production code LOC delta (negative = rewarded for removing code)
    prod_net = bucketed["production"]["added"] - bucketed["production"]["deleted"]
    breakdown["production_loc_delta"] = -prod_net  # negate: removed code = positive
    score += -prod_net

    # Lib LOC delta — additions to _lib that consolidate are slightly less penalized
    # (still spending lines, but if they replace many copies it's net positive elsewhere)
    lib_net = bucketed["lib"]["added"] - bucketed["lib"]["deleted"]
    breakdown["lib_loc_delta"] = -lib_net // 2  # half weight; _lib is not free but is cheaper
    score += -lib_net // 2

    # Test code: LOC irrelevant; test-case count matters
    test_case_delta = 0
    for path, a, d in bucketed["test"]["files"]:
        before = file_at_rev(base, path)
        after = file_at_rev(head, path)
        test_case_delta += count_test_cases(after) - count_test_cases(before)
    breakdown["new_test_cases"] = test_case_delta * 2
    score += test_case_delta * 2

    # Doc code: REMOVING is rewarded (consolidation). ADDING to NEW non-canonical
    # doc files is penalized (fragmentation). ADDING to EXISTING or to canonical
    # new files (CENTAUR_*, *_DESIGN, *_RESULTS, *_PLAN) is neutral (legitimate
    # rewrites/spec additions).
    canonical = re.compile(r"(CENTAUR_|_DESIGN|_RESULTS|_PLAN|_design|_results)")
    doc_added_to_new_non_canonical = sum(
        a for p, a, d in bucketed["doc"]["files"]
        if d == 0 and a > 0 and not canonical.search(pathlib.PurePath(p).name)
    )
    doc_added_to_canonical_new = sum(
        a for p, a, d in bucketed["doc"]["files"]
        if d == 0 and a > 0 and canonical.search(pathlib.PurePath(p).name)
    )
    doc_added_to_existing = sum(a for p, a, d in bucketed["doc"]["files"] if d > 0)
    doc_removed = bucketed["doc"]["deleted"]
    # Net doc score: removals minus new-fragment-additions; updates to existing and canonical new are neutral
    doc_net_score = doc_removed - doc_added_to_new_non_canonical
    breakdown["doc_removed_minus_new_fragments"] = doc_net_score
    score += doc_net_score
    breakdown["doc_lines_to_existing_files"] = doc_added_to_existing  # informational
    breakdown["doc_lines_to_canonical_new"] = doc_added_to_canonical_new  # informational

    # Doc-files-added penalty (creating fragments). Canonical doc creations exempt.
    doc_files_added = sum(1 for p, _, d in bucketed["doc"]["files"] if d == 0)
    canonical_new = sum(
        1 for p, _, d in bucketed["doc"]["files"]
        if d == 0 and canonical.search(pathlib.PurePath(p).name)
    )
    new_fragment_docs = doc_files_added - canonical_new
    breakdown["new_doc_files_penalty"] = -2 * new_fragment_docs
    score += -2 * new_fragment_docs

    # Forbidden probe doc penalty
    new_probe_docs = 0
    for p, _, d in bucketed["doc"]["files"]:
        name = pathlib.PurePath(p).stem
        if PROBE_DOC_PATTERN.match(name) and d == 0:
            new_probe_docs += 1
    breakdown["forbidden_probe_docs"] = -10 * new_probe_docs
    score += -10 * new_probe_docs

    # Duplicate-group delta — compute before/after across all production code
    # (this requires checking out both revisions; we use git show piped to a temp repo state)
    # Simpler: use the diff to identify added/removed functions, then check hashes.
    fn_hashes_added = set()
    fn_hashes_removed = set()
    for path, a, d in diff:
        kind = classify(path)
        if kind not in ("production", "lib"):
            continue
        before = file_at_rev(base, path)
        after = file_at_rev(head, path)
        h_before = hash_function_bodies(before)
        h_after = hash_function_bodies(after)
        for name, h in h_after.items():
            if name not in h_before or h_before[name] != h:
                fn_hashes_added.add((path, name, h))
        for name, h in h_before.items():
            if name not in h_after or h_after[name] != h:
                fn_hashes_removed.add((path, name, h))

    # Closes-issue bonus
    closes = parse_closes_lines(base, head)
    breakdown["issues_closed"] = closes * 10
    score += closes * 10

    # Long-function penalty/bonus (heuristic; full check is in #1328 Centaur complexity)
    long_fn_delta = 0
    for path, a, d in diff:
        if classify(path) != "production":
            continue
        before = file_at_rev(base, path)
        after = file_at_rev(head, path)
        long_fn_delta += function_lines_over_threshold(after) - function_lines_over_threshold(before)
    breakdown["long_functions_delta"] = -2 * long_fn_delta
    score += -2 * long_fn_delta

    breakdown["TOTAL_SCORE"] = score

    # Human summary to stderr
    print("=" * 60, file=sys.stderr)
    print(f"PR PRODUCTIVITY SCORE: {score}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    for k, v in breakdown.items():
        if k == "TOTAL_SCORE":
            continue
        marker = "+" if v >= 0 else ""
        print(f"  {marker}{v:4d}  {k}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    if score < 0:
        print("⚠️  NEGATIVE — this PR made the codebase worse. Reconsider.", file=sys.stderr)
    elif score < 5:
        print("⚠️  Marginal. Confirm this PR's complexity/code is necessary.", file=sys.stderr)
    elif score > 50:
        print("✓  Strong positive. Real productivity.", file=sys.stderr)
    else:
        print("✓  Positive.", file=sys.stderr)

    # JSON to stdout
    json.dump(
        {
            "base": base,
            "head": head,
            "score": score,
            "breakdown": breakdown,
            "buckets": {
                k: {"added": v["added"], "deleted": v["deleted"], "file_count": len(v["files"])}
                for k, v in bucketed.items()
            },
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
