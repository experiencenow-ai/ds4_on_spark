#!/usr/bin/env bash
# lane_claim_next.sh — claim the next compatible backlog issue for the calling track.
#
# Usage: lane_claim_next.sh <track-number> [comma-separated-free-hw-labels]
#   $ scripts/lane_claim_next.sh 3 hw:any-1,hw:none,hw:spark-2-3-4
#
# Behavior:
#   1. Reads the backlog, sorted P0 > P1 > P2.
#   2. Filters to issues whose hw:* label is in the free set, or is hw:none.
#   3. Skips issues with open dependencies (any #N referenced in "Depends on:" that is not closed).
#   4. Atomically claims by editing labels: remove track:backlog + status:queued,
#      add track:<N> + status:claimed.
#   5. Re-reads the issue. If another track raced and got it, retries.
#   6. Prints the claimed issue number and title, or "none" if nothing matched.

set -euo pipefail

REPO="${REPO:-experiencenow-ai/ds4_on_spark}"

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <track-number> [comma-separated-free-hw-labels]" >&2
    exit 2
fi

TRACK="$1"
FREE_HW="${2:-hw:none}"

# Convert comma-separated to space-separated bash array
IFS=',' read -ra FREE_HW_ARR <<< "$FREE_HW"
# hw:none is always implicitly free
HW_NONE_FOUND=0
for h in "${FREE_HW_ARR[@]}"; do
    [ "$h" = "hw:none" ] && HW_NONE_FOUND=1
done
if [ "$HW_NONE_FOUND" = "0" ]; then
    FREE_HW_ARR+=("hw:none")
fi

is_hw_free() {
    local needed="$1"
    for h in "${FREE_HW_ARR[@]}"; do
        [ "$h" = "$needed" ] && return 0
    done
    return 1
}

deps_open() {
    local issue_num="$1"
    # Extract dependency issue numbers from the body's "Depends on:" line.
    local body
    body=$(gh issue view "$issue_num" --repo "$REPO" --json body --jq '.body' 2>/dev/null || echo "")
    local deps
    deps=$(printf '%s\n' "$body" | grep -i "Depends on:" | grep -oE '#[0-9]+' | tr -d '#' || true)
    for dep in $deps; do
        local state
        state=$(gh issue view "$dep" --repo "$REPO" --json state --jq '.state' 2>/dev/null || echo "OPEN")
        if [ "$state" != "CLOSED" ]; then
            return 0
        fi
    done
    return 1
}

attempt_claim() {
    local issue_num="$1"
    if ! gh issue edit "$issue_num" --repo "$REPO" \
            --remove-label "track:backlog" --add-label "track:${TRACK}" \
            --remove-label "status:queued" --add-label "status:claimed" \
            >/dev/null 2>&1; then
        return 1
    fi
    # Verify our track label is the only track:* label and status is claimed.
    local labels
    labels=$(gh issue view "$issue_num" --repo "$REPO" --json labels --jq '.labels | map(.name) | join(",")')
    local track_labels
    track_labels=$(echo "$labels" | tr ',' '\n' | grep -c "^track:" || true)
    if [ "$track_labels" -ne 1 ] || ! echo "$labels" | tr ',' '\n' | grep -qx "track:${TRACK}"; then
        # Race lost. Rollback.
        gh issue edit "$issue_num" --repo "$REPO" \
            --remove-label "track:${TRACK}" --add-label "track:backlog" \
            --remove-label "status:claimed" --add-label "status:queued" \
            >/dev/null 2>&1 || true
        return 1
    fi
    return 0
}

for prio in P0 P1 P2; do
    candidates=$(gh issue list --repo "$REPO" \
        --label "track:backlog" --label "status:queued" --label "prio:${prio}" \
        --state open --json number,labels \
        --jq '.[] | {n: .number, hw: (.labels | map(.name) | map(select(startswith("hw:"))) | .[0])}' \
        2>/dev/null || true)
    if [ -z "$candidates" ]; then continue; fi
    echo "$candidates" | while read -r row; do
        n=$(echo "$row" | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['n'])")
        hw=$(echo "$row" | python3 -c "import json,sys; print(json.loads(sys.stdin.read()).get('hw') or 'hw:none')")
        if ! is_hw_free "$hw"; then continue; fi
        if deps_open "$n"; then continue; fi
        if attempt_claim "$n"; then
            title=$(gh issue view "$n" --repo "$REPO" --json title --jq '.title')
            echo "CLAIMED #$n $title  [hw=$hw prio=$prio]"
            # Post a claim comment
            gh issue comment "$n" --repo "$REPO" \
                --body "/claim track:${TRACK}. Acceptance gates acknowledged. Hardware reserved: ${hw}. First evidence within 30 min of starting." \
                >/dev/null
            exit 0
        fi
    done
done

echo "none"
