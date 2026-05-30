#!/usr/bin/env bash
set -euo pipefail

QUEUE_DIR="${QUEUE_DIR:-/tmp/ds4_v2_queue}"
PROFILES_DIR="${PROFILES_DIR:-profiles/models}"
TOPOLOGY="${TOPOLOGY:-profiles/topology/static_sparks.json}"
NODE_ID="${NODE_ID:-spark0}"
LIMIT="${LIMIT:-48}"
CONCURRENCY="${CONCURRENCY:-48}"
KV_CAPACITY_BYTES="${KV_CAPACITY_BYTES:-0}"
BATCH_LINGER_S="${BATCH_LINGER_S:-0.05}"

DEFAULT_PIPELINE_BASE_URLS_JSON='{"qwen27_bf16_pp8":"http://127.0.0.1:8101","qwen3_6_27b_bf16_pp8_efficient_v1":"http://127.0.0.1:8101","Qwen/Qwen3.6-27B":"http://127.0.0.1:8101","dsv4_flash_pp8":"http://127.0.0.1:8102","dsv4_vllm_mtp_pp8_smartest_v1":"http://127.0.0.1:8102","deepseek-ai/DeepSeek-V4-Flash":"http://127.0.0.1:8102"}'
export DS4_PIPELINE_BASE_URLS_JSON="${DS4_PIPELINE_BASE_URLS_JSON:-${DEFAULT_PIPELINE_BASE_URLS_JSON}}"

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
