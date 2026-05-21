#!/usr/bin/env bash
# lane_status.sh — print current track allocation and idle/active counts.
# Reads issues via gh CLI; assumes you are in the ds4_on_spark repo with gh authenticated.

set -euo pipefail

REPO="${REPO:-experiencenow-ai/ds4_on_spark}"

echo "=== Track work in flight ==="
printf "%-12s %-18s %s\n" "TRACK" "STATUS" "ISSUE"
for track in 1 2 3 4; do
    for status in in-progress claimed blocked; do
        gh issue list --repo "$REPO" \
            --label "track:${track}" --label "status:${status}" \
            --state open --json number,title \
            --jq ".[] | \"track:${track}     status:${status}    #\\(.number) \\(.title)\"" || true
    done
done

echo
echo "=== Backlog (queued, by priority) ==="
printf "%-6s %-14s %s\n" "PRIO" "HW" "ISSUE"
for prio in P0 P1 P2; do
    gh issue list --repo "$REPO" \
        --label "track:backlog" --label "status:queued" --label "prio:${prio}" \
        --state open --json number,title,labels \
        --jq ".[] | \"prio:${prio}    \\(.labels | map(.name) | map(select(startswith(\"hw:\"))) | join(\",\"))    #\\(.number) \\(.title)\"" || true
done

echo
echo "=== Coordination issue (latest hardware table) ==="
COORD_NUM=$(gh issue list --repo "$REPO" --label "meta:coordination" --state open --json number --jq '.[0].number')
if [ -n "$COORD_NUM" ] && [ "$COORD_NUM" != "null" ]; then
    echo "  Coordination issue: #$COORD_NUM"
    echo "  Latest comment (truncated):"
    gh issue view "$COORD_NUM" --repo "$REPO" --comments \
        --json comments --jq '.comments[-1].body' 2>/dev/null | head -25 | sed 's/^/    /'
else
    echo "  No coordination issue found. Bootstrap may not be complete."
fi
