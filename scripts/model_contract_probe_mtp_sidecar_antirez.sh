#!/usr/bin/env bash
set -euo pipefail

# Pinned antirez sidecar (DeepSeek V4 Flash MTP) used as the contract reference for
# `general.architecture=deepseek4_mtp_support` + the compact 32-tensor `mtp.0.*` table.
#
# This script performs a metadata-only validation via HTTP range reads (no full model download).
#
# Override with:
#   SIDECAR_URL=... ./scripts/model_contract_probe_mtp_sidecar_antirez.sh

SIDECAR_URL="${SIDECAR_URL:-https://huggingface.co/antirez/deepseek-v4-gguf/resolve/9cb905d99321dbefb0e7c63fdb9bbd4d8aa7126a/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf}"
PAYLOAD_SAMPLE_BYTES="${PAYLOAD_SAMPLE_BYTES:-64}"

python3 scripts/model_contract_probe_mtp_sidecar.py --url "$SIDECAR_URL" --json --expect-deepseek-v4-flash --payload-sample-bytes "$PAYLOAD_SAMPLE_BYTES"
