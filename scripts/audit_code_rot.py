#!/usr/bin/env python3
"""Audit script for code duplication and dead bloat in scripts/.

Outputs a ranked list of:
- Functions whose body hashes to the same value in 2+ files (true DRY violations)
- Files in obviously-deprecated patterns (per-day probe docs, vXX notes)
- Large files (>500 LOC) that may warrant splitting

Run from repo root. Designed to be CI-runnable.

Modes:
- Default (enforcement): exits nonzero on any violation. CI fails.
- `--baseline-snapshot` writes the current violation set to .audit-baseline.json
  and exits 0. Use ONCE during the cleanup transition.
- Default mode honors .audit-baseline.json: any violation in the baseline is
  reported but does not fail the exit code. Any NEW violation fails CI.
  This way the cleanup is incremental but no new rot is allowed.

Why it exists: ct direction 2026-05-23 - "every line of code needs to be
justified." We cannot enforce that without measuring it.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import pathlib
import re
import sys
from collections import defaultdict

from audit_code_similarity import DEFAULT_MIN_FUNCTION_LINES as DEFAULT_SIMILARITY_MIN_LINES
from audit_code_similarity import DEFAULT_SIMILARITY_THRESHOLD
from audit_code_similarity import normalize_pair_key
from audit_code_similarity import pair_keys
from audit_code_similarity import resolve_centaur_root
from audit_code_similarity import run_similarity_audit


def _normalize_body(body_nodes: list[ast.stmt]) -> str:
    """Hash a function body for cross-file equality detection.

    Strips docstrings and comments; preserves logic-bearing statements.
    """
    pieces = []
    for node in body_nodes:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue  # docstring
        pieces.append(ast.dump(node, annotate_fields=False, include_attributes=False))
    return hashlib.md5("\n".join(pieces).encode()).hexdigest()[:10]


def find_duplicate_functions(scripts_dir: pathlib.Path) -> dict[str, list[tuple[str, str]]]:
    """Return {body_hash: [(file, func_name), ...]} for any hash appearing 2+ times."""
    by_hash: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path in sorted(scripts_dir.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip trivial bodies (<3 stmts) to avoid noise from `def main()`
                if len(node.body) < 3:
                    continue
                h = _normalize_body(node.body)
                by_hash[h].append((str(path.relative_to(scripts_dir.parent)), node.name))
    return {h: locs for h, locs in by_hash.items() if len(locs) > 1}


PROBE_DOC_PATTERN = re.compile(
    # any markdown file whose name ends with a date/timestamp suffix is
    # almost certainly a per-iteration probe/status doc — the LANES.md
    # forbidden 'vXX notes' anti-pattern, just with timestamp encoding.
    r".*-\d{4}-\d{2}-\d{2}(T\d{4}Z)?$"      # any-name-YYYY-MM-DD[THHMMZ]
    r"|^baseline-.*\d{4}-\d{2}-\d{2}"        # baseline reports with date in the middle
    r"|^spark.*-probe.*"                      # spark*-probe-anything
    r"|.*-iteration-\d"
    r"|.*-v\d+-notes"
)


def find_probe_docs(docs_dir: pathlib.Path) -> list[pathlib.Path]:
    out = []
    for path in sorted(docs_dir.glob("*.md")):
        if PROBE_DOC_PATTERN.match(path.name):
            out.append(path)
    return out


def find_large_scripts(scripts_dir: pathlib.Path, threshold: int = 500) -> list[tuple[int, pathlib.Path]]:
    rows = []
    for path in scripts_dir.glob("*.py"):
        n = sum(1 for _ in path.read_text().splitlines())
        if n > threshold:
            rows.append((n, path))
    return sorted(rows, reverse=True)


def load_baseline(repo: pathlib.Path) -> dict | None:
    p = repo / ".audit-baseline.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def write_baseline(repo: pathlib.Path, dups: dict, probes: list[pathlib.Path], similarity: dict) -> None:
    p = repo / ".audit-baseline.json"
    payload = {
        "duplicate_function_hashes": sorted(dups.keys()),
        "duplicate_function_counts": {h: len(locs) for h, locs in dups.items()},
        "probe_docs": sorted(str(d.relative_to(repo)) for d in probes),
        "similarity_threshold": similarity.get("threshold"),
        "similarity_function_pairs": sorted(pair_keys(similarity.get("pairs", []))),
    }
    p.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-snapshot", action="store_true",
                        help="Write current violation set as the baseline and exit 0.")
    parser.add_argument("--centaur-root", help="Path to a Centaur checkout containing centaur.py. Defaults to CENTAUR_REPO or ../centaur.")
    parser.add_argument("--similarity-threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD)
    parser.add_argument("--similarity-min-lines", type=int, default=DEFAULT_SIMILARITY_MIN_LINES)
    args = parser.parse_args()

    repo = pathlib.Path(__file__).resolve().parent.parent
    scripts_dir = repo / "scripts"
    docs_dir = repo / "docs"

    print("=" * 70)
    print("Code-rot audit — every line should be justified")
    print("=" * 70)

    baseline = load_baseline(repo)
    dups = find_duplicate_functions(scripts_dir)
    probes = find_probe_docs(docs_dir)
    try:
        centaur_root = resolve_centaur_root(repo, args.centaur_root)
        similarity = run_similarity_audit(
            repo,
            centaur_root,
            float(args.similarity_threshold),
            int(args.similarity_min_lines),
            5,
            200,
        )
    except RuntimeError as exc:
        centaur_root = pathlib.Path("<missing-centaur>")
        similarity = {
            "degraded": True,
            "reason": str(exc),
            "pairs": [],
            "elapsed_seconds": 0.0,
            "threshold": float(args.similarity_threshold),
            "function_count": 0,
            "centaur_import": "degraded: centaur repo unavailable",
        }

    if args.baseline_snapshot:
        write_baseline(repo, dups, probes, similarity)
        print(f"\nBaseline snapshot written:")
        print(f"  duplicate-function hashes: {len(dups)}")
        print(f"  forbidden probe docs:      {len(probes)}")
        print(f"  similarity pairs:          {len(similarity.get('pairs', []))}")
        print(f"\nFuture audit runs will fail on NEW violations only.")
        return 0

    # 1. Duplicate function bodies
    print("\n1. Function bodies with identical hash across 2+ files (DRY violations):")
    if not dups:
        print("   (none — well done)")
    else:
        total_dup_funcs = sum(len(locs) - 1 for locs in dups.values())
        print(f"   {len(dups)} distinct duplicate-body groups, {total_dup_funcs} extra copies")
        for h, locs in sorted(dups.items(), key=lambda kv: -len(kv[1]))[:25]:
            new = baseline is None or h not in baseline.get("duplicate_function_hashes", [])
            marker = " *** NEW ***" if new and baseline is not None else ""
            print(f"   [{h}] {len(locs)} copies of `{locs[0][1]}`:{marker}")
            for f, n in locs:
                print(f"        {f}:def {n}()")

    # 2. Forbidden per-day probe docs
    print("\n2. Forbidden per-day/per-iteration probe docs (LANES.md anti-pattern):")
    if not probes:
        print("   (none)")
    else:
        print(f"   {len(probes)} files, total size: {sum(p.stat().st_size for p in probes) // 1024} KB")
        for p in probes[:10]:
            rel = str(p.relative_to(repo))
            new = baseline is None or rel not in baseline.get("probe_docs", [])
            marker = " *** NEW ***" if new and baseline is not None else ""
            print(f"        {rel}{marker}")
        if len(probes) > 10:
            print(f"        ... and {len(probes) - 10} more")

    print("\n3. Centaur near-duplicate function similarity:")
    print(f"   import: {similarity.get('centaur_import')}")
    print(f"   centaur_root: {centaur_root}")
    print(f"   threshold={similarity.get('threshold')} functions={similarity.get('function_count')} elapsed={similarity.get('elapsed_seconds')}s")
    similarity_pairs = similarity.get("pairs", []) if isinstance(similarity.get("pairs"), list) else []
    if not similarity_pairs:
        print("   (none)")
    else:
        print(f"   {len(similarity_pairs)} pairs at or above threshold")
        baseline_similarity = set()
        if baseline is not None:
            baseline_similarity = {normalize_pair_key(str(key)) for key in baseline.get("similarity_function_pairs", [])}
        for pair in similarity_pairs[:25]:
            key = normalize_pair_key(str(pair.get("left", "")) + " <=> " + str(pair.get("right", "")))
            new = baseline is None or key not in baseline_similarity
            marker = " *** NEW ***" if new and baseline is not None else ""
            print(f"   {float(pair.get('score', 0.0)):.3f} {pair.get('reason')}:{marker}")
            print(f"        {pair.get('left')}")
            print(f"        {pair.get('right')}")

    # 3. Largest scripts (potential split candidates)
    print("\n4. Largest scripts (>500 LOC, candidates for decomposition):")
    big = find_large_scripts(scripts_dir, 500)
    if not big:
        print("   (none)")
    else:
        for n, p in big[:15]:
            print(f"   {n:5d} {p.relative_to(repo)}")

    # 4. Aggregate totals
    print("\n5. Aggregate totals:")
    scripts_loc = sum(sum(1 for _ in p.read_text().splitlines()) for p in scripts_dir.glob("*.py"))
    docs_count = sum(1 for _ in docs_dir.glob("*.md"))
    docs_size_kb = sum(p.stat().st_size for p in docs_dir.glob("*.md")) // 1024
    print(f"   scripts/*.py: {len(list(scripts_dir.glob('*.py')))} files, {scripts_loc} LOC")
    print(f"   docs/*.md:    {docs_count} files, {docs_size_kb} KB")

    # 5. Exit code: nonzero only on NEW violations (when baseline exists), or
    #    on any violation (when baseline is missing — first-run enforcement)
    if baseline is None:
        if dups or probes:
            print("\n*** FAILURES PRESENT ***  No .audit-baseline.json yet. Run with")
            print("    --baseline-snapshot ONCE to record the current state, then")
            print("    fix violations incrementally. Future PRs cannot ADD new ones.")
            return 1
        return 0
    # Baseline exists: check for new violations only.
    # Two kinds of "new":
    #   (a) A duplicate-function hash that did not exist in the baseline at all.
    #   (b) An existing hash whose copy COUNT increased (someone added another duplicate).
    baseline_hashes = set(baseline.get("duplicate_function_hashes", []))
    baseline_counts = baseline.get("duplicate_function_counts", {})
    baseline_probes = set(baseline.get("probe_docs", []))
    baseline_similarity = {normalize_pair_key(str(key)) for key in baseline.get("similarity_function_pairs", [])}
    new_dup_hashes = set(dups.keys()) - baseline_hashes
    grown_dup_hashes = {
        h for h, locs in dups.items()
        if h in baseline_hashes and len(locs) > baseline_counts.get(h, 0)
    }
    new_probes = set(str(p.relative_to(repo)) for p in probes) - baseline_probes
    new_similarity = pair_keys(similarity_pairs) - baseline_similarity
    if new_dup_hashes or grown_dup_hashes or new_probes or new_similarity:
        print(f"\n*** NEW VIOLATIONS ***")
        print(f"  brand-new duplicate-function groups: {len(new_dup_hashes)}")
        print(f"  existing groups that GREW (more copies added): {len(grown_dup_hashes)}")
        print(f"  new forbidden probe docs:             {len(new_probes)}")
        print(f"  new Centaur similarity pairs:         {len(new_similarity)}")
        if grown_dup_hashes:
            print(f"\n  Grown groups (copy count increased):")
            for h in sorted(grown_dup_hashes):
                print(f"    [{h}] was {baseline_counts.get(h, 0)} copies, now {len(dups[h])}")
        if new_similarity:
            print(f"\n  New Centaur similarity pairs:")
            for key in sorted(new_similarity)[:25]:
                print(f"    {key}")
        print(f"\nNo new rot allowed. Fix or remove these before this PR can land.")
        return 1
    print(f"\nOK. No new violations vs baseline. ({len(dups)} pre-existing dup groups,")
    print(f"{len(probes)} pre-existing probe docs, {len(similarity_pairs)} pre-existing similarity pairs remain to clean up.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
