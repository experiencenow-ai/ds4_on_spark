#!/usr/bin/env bash
set -euo pipefail

HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8700}
DS4_NVME_ROOT=${DS4_NVME_ROOT:-$HOME/ds4_nvme}
QUEUE_DIR=${QUEUE_DIR:-$DS4_NVME_ROOT/ds4_queue}
PROFILES_DIR=${PROFILES_DIR:-profiles/models}
TOPOLOGY=${TOPOLOGY:-profiles/topology/static_sparks.json}
RUNNER_KIND=${RUNNER_KIND:-pipeline}
SYNC_TIMEOUT_S=${SYNC_TIMEOUT_S:-${DS4_API_SYNC_TIMEOUT_S:-3600}}

cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-$PWD/src}"

exec python3 -m ds4_infer.api \
    --host "$HOST" \
    --port "$PORT" \
    --queue-dir "$QUEUE_DIR" \
    --profiles-dir "$PROFILES_DIR" \
    --topology "$TOPOLOGY" \
    --runner-kind "$RUNNER_KIND" \
    --sync-timeout-s "$SYNC_TIMEOUT_S"
