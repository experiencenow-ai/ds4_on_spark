#!/usr/bin/env bash
# lane_release_hw.sh — release a track's hardware reservation via a comment on
# the coordination issue. Use this when finishing a hardware-bound task or
# transitioning to status:blocked.
#
# Usage: lane_release_hw.sh <track-number> <hw-label> [reason]
#   $ scripts/lane_release_hw.sh 3 hw:spark-2-3-4 "K=8 acceptance failed, posting findings"

set -euo pipefail

REPO="${REPO:-experiencenow-ai/ds4_on_spark}"

if [ "$#" -lt 2 ]; then
    echo "usage: $0 <track-number> <hw-label> [reason]" >&2
    exit 2
fi

TRACK="$1"
HW="$2"
REASON="${3:-task complete}"

COORD_NUM=$(gh issue list --repo "$REPO" --label "meta:coordination" --state open --json number --jq '.[0].number')
if [ -z "$COORD_NUM" ] || [ "$COORD_NUM" = "null" ]; then
    echo "no coordination issue found" >&2
    exit 1
fi

gh issue comment "$COORD_NUM" --repo "$REPO" \
    --body "/release-hw track:${TRACK} ${HW} — ${REASON}"

echo "released ${HW} from track:${TRACK} on coordination issue #${COORD_NUM}"
echo "next track to claim work needing ${HW} should read the comment thread and add an updated hardware-table comment."
