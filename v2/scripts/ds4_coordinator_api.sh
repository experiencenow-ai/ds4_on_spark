#!/usr/bin/env bash
set -euo pipefail

HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8700}
QUEUE_DIR=${QUEUE_DIR:-/home/$USER/ds4_queue}
PROFILES_DIR=${PROFILES_DIR:-profiles/models}
TOPOLOGY=${TOPOLOGY:-profiles/topology/static_sparks.json}
RUNNER_KIND=${RUNNER_KIND:-pipeline}

cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-$PWD/src}"

exec python3 -m ds4_infer.api \
    --host "$HOST" \
    --port "$PORT" \
    --queue-dir "$QUEUE_DIR" \
    --profiles-dir "$PROFILES_DIR" \
    --topology "$TOPOLOGY" \
    --runner-kind "$RUNNER_KIND"
