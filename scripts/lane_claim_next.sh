#!/usr/bin/env bash
# lane_claim_next.sh — claim the next backlog issue whose hardware is currently free.
#
# Usage: lane_claim_next.sh <track-number>
#   $ scripts/lane_claim_next.sh 3
#
# The script reads the actual hardware reservation state from open in-progress
# issues (any hw:spark-N label on an in-progress issue reserves that Spark).
# It then finds the highest-priority backlog issue whose required Sparks are
# all currently free, and atomically claims it for the given track.
#
# Required labels on a backlog issue: track:backlog + status:queued + prio:P{0,1,2}
# Hardware requirement: zero or more hw:spark-N labels (the Sparks the issue needs).
#                       hw:none means "no Spark required" (always claimable).
#                       hw:any-1 / hw:any-3 means "needs N free Sparks of any group."
#
# Behavior:
#   1. Compute the current Spark reservation table from in-progress issues.
#   2. Walk P0 -> P1 -> P2 backlog.
#   3. For each candidate, check: are all its required Sparks currently free,
#      and are all its declared dependencies closed?
#   4. Atomically claim by labels: track:backlog -> track:<N>, status:queued -> status:claimed.
#   5. The hw:spark-N labels stay on the issue; they become reservations the
#      moment status flips to in-progress.
#   6. Print the claimed issue number + which Sparks got reserved.
#
# The script has no awareness of any "agent affinity" or "specialty." It is
# pure hardware-availability matching.

set -euo pipefail

REPO="${REPO:-experiencenow-ai/ds4_on_spark}"
GH_BIN="${GH_BIN:-gh}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ "$#" -lt 1 ]; then
    echo "usage: $0 <track-number>" >&2
    exit 2
fi

TRACK="$1"

in_progress_json=$("$GH_BIN" issue list --repo "$REPO" \
    --label "status:in-progress" --state open --limit 200 \
    --json number,title,labels)

reserved_sparks=$(echo "$in_progress_json" | "$PYTHON_BIN" -c "
import json, sys
data = json.load(sys.stdin)
reserved = set()
for d in data:
    for item in d.get('labels', []):
        label = item.get('name', item) if isinstance(item, dict) else item
        if label.startswith('hw:spark-'):
            try:
                n = int(label.split('-')[-1])
                if 0 <= n <= 7:
                    reserved.add(n)
            except ValueError:
                pass
print(' '.join(str(n) for n in sorted(reserved)))
")

reserved_count=$(echo "$reserved_sparks" | wc -w | tr -d ' ')
free_count=$((8 - reserved_count))

is_spark_free() {
    local sn="$1"
    for r in $reserved_sparks; do
        [ "$r" = "$sn" ] && return 1
    done
    return 0
}

deps_open() {
    local issue_num="$1"
    local body
    body=$("$GH_BIN" issue view "$issue_num" --repo "$REPO" --json body --jq '.body' 2>/dev/null || echo "")
    local deps
    deps=$(printf '%s\n' "$body" | grep -iE "^\*\*Depends on:\*\*|^Depends on:" -A 5 \
        | grep -oE '#[0-9]+' | tr -d '#' || true)
    for dep in $deps; do
        local state
        state=$("$GH_BIN" issue view "$dep" --repo "$REPO" --json state --jq '.state' 2>/dev/null || echo "OPEN")
        if [ "$state" != "CLOSED" ]; then
            return 0
        fi
    done
    return 1
}

hw_available() {
    local labels_csv="$1"
    local needs_any_1=0 needs_any_3=0
    local needed_sparks=""

    for label in $(echo "$labels_csv" | tr ',' ' '); do
        case "$label" in
            hw:none) ;;
            hw:any-1) needs_any_1=1 ;;
            hw:any-3) needs_any_3=1 ;;
            hw:spark-[0-7])
                sn="${label#hw:spark-}"
                needed_sparks="$needed_sparks $sn" ;;
            hw:spark-*-*)
                echo "  (skipping issue: uses deprecated composite label $label)" >&2
                return 1 ;;
        esac
    done

    for sn in $needed_sparks; do
        if ! is_spark_free "$sn"; then return 1; fi
    done

    if [ "$needs_any_1" = "1" ] && [ "$free_count" -lt 1 ]; then return 1; fi
    if [ "$needs_any_3" = "1" ] && [ "$free_count" -lt 3 ]; then return 1; fi

    return 0
}

attempt_claim() {
    local issue_num="$1"
    local hw_csv="$2"
    if ! "$GH_BIN" issue edit "$issue_num" --repo "$REPO" \
            --remove-label "track:backlog" --add-label "track:${TRACK}" \
            --remove-label "status:queued" --add-label "status:claimed" \
            >/dev/null 2>&1; then
        return 1
    fi
    local labels
    labels=$("$GH_BIN" issue view "$issue_num" --repo "$REPO" --json labels --jq '.labels | map(.name) | join(",")')
    local track_count
    track_count=$(echo "$labels" | tr ',' '\n' | grep -c "^track:" || true)
    if [ "$track_count" -ne 1 ] || ! echo "$labels" | tr ',' '\n' | grep -qx "track:${TRACK}"; then
        "$GH_BIN" issue edit "$issue_num" --repo "$REPO" \
            --remove-label "track:${TRACK}" --add-label "track:backlog" \
            --remove-label "status:claimed" --add-label "status:queued" \
            >/dev/null 2>&1 || true
        return 1
    fi
    return 0
}

echo "Reserved Sparks right now: [${reserved_sparks:-none}]; free: $free_count of 8"

for prio in P0 P1 P2; do
    candidates=$("$GH_BIN" issue list --repo "$REPO" \
        --label "track:backlog" --label "status:queued" --label "prio:${prio}" \
        --state open --limit 200 --json number,title,labels \
        2>/dev/null || true)
    if [ -z "$candidates" ]; then continue; fi
    candidate_rows=$(echo "$candidates" | "$PYTHON_BIN" -c "
import json, sys
data = json.load(sys.stdin)
for d in data:
    labels = []
    for item in d.get('labels', []):
        labels.append(item.get('name', item) if isinstance(item, dict) else item)
    hw = ','.join([label for label in labels if label.startswith('hw:')]) or 'hw:none'
    print(f\"{d['number']}\t{d.get('title', '')}\t{hw}\")
")
    if [ -z "$candidate_rows" ]; then continue; fi
    while IFS="$(printf '\t')" read -r n title hw_csv; do
        if ! hw_available "$hw_csv"; then continue; fi
        if deps_open "$n"; then continue; fi
        if attempt_claim "$n" "$hw_csv"; then
            echo "CLAIMED #$n $title  [hw=$hw_csv prio=$prio]"
            "$GH_BIN" issue comment "$n" --repo "$REPO" \
                --body "/claim track:${TRACK}. Acceptance gates acknowledged. Hardware reservation: \`${hw_csv}\` — these Sparks will be reserved the moment this issue flips to status:in-progress. First evidence within 30 min of starting." \
                >/dev/null
            exit 0
        fi
    done <<< "$candidate_rows"
done

echo "none"
