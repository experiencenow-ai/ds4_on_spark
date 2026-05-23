#!/usr/bin/env python3
"""Productivity leaderboard for tracks (xhigh agents).

Reads merged PRs from GitHub, scores each via audit_pr_productivity.py logic,
attributes score to the track:N label on the closing issue, and reports a
cumulative leaderboard.

ct direction 2026-05-23:
- Tracks earn bonus points for reducing code, increasing functionality, and
  reducing complexity.
- Pure-volume metrics (lines written) are the WRONG signal. Functionality
  per unit complexity is the right one.

Usage:
    python3 scripts/productivity_leaderboard.py [--since YYYY-MM-DD] [--limit N]

Outputs a Markdown table to stdout suitable for pasting into the coordination
issue.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from collections import defaultdict


def gh_get(path: str, pat: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def score_pr(base_sha: str, head_sha: str) -> int:
    """Run audit_pr_productivity.py and parse score."""
    here = os.path.dirname(os.path.abspath(__file__))
    out = subprocess.check_output(
        [sys.executable, os.path.join(here, "audit_pr_productivity.py"), base_sha, head_sha],
        text=True,
        cwd=os.path.dirname(here),
        stderr=subprocess.DEVNULL,
    )
    data = json.loads(out)
    return data["score"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2026-05-21", help="ISO date")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--repo", default="experiencenow-ai/ds4_on_spark")
    args = parser.parse_args()

    pat = os.environ.get("PAT") or os.environ.get("GITHUB_TOKEN")
    if not pat:
        print("error: set PAT or GITHUB_TOKEN env var", file=sys.stderr)
        return 1

    # Get merged PRs
    prs = gh_get(
        f"/repos/{args.repo}/pulls?state=closed&sort=updated&direction=desc&per_page={args.limit}",
        pat,
    )

    rows = []
    by_track = defaultdict(lambda: {"score": 0, "prs": 0, "merged": []})
    for pr in prs:
        if not pr["merged_at"]:
            continue
        if pr["merged_at"][:10] < args.since:
            continue
        # Find track from branch name or PR comments
        branch = pr["head"]["ref"]
        track = "?"
        for t in ("track1", "track2", "track3", "track4", "track5", "track6"):
            if t in branch:
                track = f"track:{t[-1]}"
                break
        # Score
        try:
            score = score_pr(pr["base"]["sha"], pr["merge_commit_sha"])
        except subprocess.CalledProcessError:
            continue
        except Exception as e:
            print(f"  warn: PR #{pr['number']} scoring failed: {e}", file=sys.stderr)
            continue
        rows.append(
            {
                "pr": pr["number"],
                "track": track,
                "score": score,
                "title": pr["title"][:55],
                "merged_at": pr["merged_at"],
            }
        )
        by_track[track]["score"] += score
        by_track[track]["prs"] += 1
        by_track[track]["merged"].append(pr["number"])

    # Per-PR table
    print(f"## Productivity scores — PRs merged since {args.since}\n")
    print("| PR | Track | Score | Title |")
    print("|---:|---|---:|---|")
    for r in sorted(rows, key=lambda x: -x["score"]):
        marker = "🏆 " if r["score"] > 1000 else ("⚠️ " if r["score"] < 0 else "")
        print(f"| #{r['pr']} | {r['track']} | {marker}{r['score']:+d} | {r['title']} |")

    # Per-track totals
    print(f"\n## Cumulative track scores\n")
    print("| Track | Cumulative score | PRs merged |")
    print("|---|---:|---:|")
    for track, data in sorted(by_track.items(), key=lambda kv: -kv[1]["score"]):
        print(f"| {track} | {data['score']:+d} | {data['prs']} |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
