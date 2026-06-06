#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V2_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DS4_NVME_ROOT="${DS4_NVME_ROOT:-$HOME/ds4_nvme}"
QUEUE_DIR="${QUEUE_DIR:-$DS4_NVME_ROOT/ds4_queue}"
PROFILES_DIR="${PROFILES_DIR:-profiles/models}"
TOPOLOGY="${TOPOLOGY:-profiles/topology/static_sparks.json}"
NODE_ID="${NODE_ID:-spark0}"
LIMIT="${LIMIT:-32}"
CONCURRENCY="${CONCURRENCY:-32}"
KV_CAPACITY_BYTES="${KV_CAPACITY_BYTES:-0}"
BATCH_LINGER_S="${BATCH_LINGER_S:-0.05}"

export PYTHONPATH="$V2_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$V2_ROOT"
if [ -z "${DS4_PIPELINE_BASE_URLS_JSON:-}" ]; then
	DS4_PIPELINE_BASE_URLS_JSON="$(python3 -c 'import json; from ds4_infer.topology import SparkTopology; topology=SparkTopology.load("'"$TOPOLOGY"'"); urls={}; [urls.update({service.service_id: service.api_base_url, service.profile_id: service.api_base_url, service.model_id: service.api_base_url}) for service in topology.pipeline_services.values()]; print(json.dumps(urls, separators=(",", ":"), sort_keys=True))')"
	export DS4_PIPELINE_BASE_URLS_JSON
fi

exec python3 -m ds4_infer.cli queue-worker \
    --queue-dir "${QUEUE_DIR}" \
    --profiles-dir "${PROFILES_DIR}" \
    --topology "${TOPOLOGY}" \
    --node-id "${NODE_ID}" \
    --runner pipeline \
    --limit "${LIMIT}" \
    --concurrency "${CONCURRENCY}" \
    --kv-capacity-bytes "${KV_CAPACITY_BYTES}" \
    --batch-linger-s "${BATCH_LINGER_S}" \
    --worker-id "${WORKER_ID:-spark0-pipeline-gateway}" \
    --loop
