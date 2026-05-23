#!/usr/bin/env bash
# lane_hardware_free.sh — report which Sparks are reserved vs free right now.
#
# A Spark is reserved if any open issue with status:in-progress carries its
# per-node hw:spark-N label. Otherwise free.
#
# Output: one line per Spark, "spark-N: free" or "spark-N: reserved by #M (title)".
#
# Usage: scripts/lane_hardware_free.sh
#
# This is the source of truth for "what hardware can I claim right now."
# Agents MUST run this (or equivalent gh CLI query) before claiming any
# hw:spark-N issue. The issue's hardware list must be entirely "free" before
# the agent applies status:claimed.

set -euo pipefail

REPO="${REPO:-experiencenow-ai/ds4_on_spark}"

if ! command -v gh >/dev/null 2>&1; then
    echo "error: gh CLI not installed; install or use the GitHub API directly" >&2
    exit 1
fi

# Pull all open in-progress issues and their labels
in_progress_json=$(gh api -X GET "repos/$REPO/issues" \
    -f state=open -f labels=status:in-progress -f per_page=100 \
    --jq '[.[] | select(.pull_request == null) | {number, title, labels: [.labels[].name]}]')

for n in 0 1 2 3 4 5 6 7; do
    reservers=$(echo "$in_progress_json" | \
        python3 -c "
import json, sys
data = json.load(sys.stdin)
label = 'hw:spark-$n'
hits = [d for d in data if label in d['labels']]
if not hits:
    print('free')
else:
    print('; '.join([f\"#{h['number']} ({h['title'][:50]})\" for h in hits]))
")
    if [ "$reservers" = "free" ]; then
        printf "  spark-%d: free\n" "$n"
    else
        printf "  spark-%d: RESERVED by %s\n" "$n" "$reservers"
    fi
done

# Also report any-N capacity:
free_count=$(echo "$in_progress_json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
reserved = set()
for d in data:
    for label in d['labels']:
        if label.startswith('hw:spark-') and label.count('-') == 2:
            try:
                n = int(label.split('-')[-1])
                reserved.add(n)
            except ValueError:
                pass
print(8 - len(reserved))
")
printf "\n  any-N capacity: %d free Sparks of 8\n" "$free_count"
