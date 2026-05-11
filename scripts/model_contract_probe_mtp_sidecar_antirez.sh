#!/usr/bin/env bash
set -euo pipefail

# Pinned antirez sidecar (DeepSeek V4 Flash MTP) used as the contract reference for
# `general.architecture=deepseek4_mtp_support` + the compact 32-tensor `mtp.0.*` table.
#
# This script performs a metadata-only validation via HTTP range reads (no full model download).
#
# Override with:
#   SIDECAR_URL=... ./scripts/model_contract_probe_mtp_sidecar_antirez.sh

SIDECAR_URL="${SIDECAR_URL:-https://huggingface.co/antirez/deepseek-v4-gguf/resolve/c198a70525f1856f1bf50448f163471692c881f8/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf}"
SIDECAR_EXPECT_FILE_SIZE="${SIDECAR_EXPECT_FILE_SIZE:-3807602400}"
PAYLOAD_SAMPLE_BYTES="${PAYLOAD_SAMPLE_BYTES:-64}"

python3 scripts/model_contract_probe_mtp_sidecar.py \
	--url "$SIDECAR_URL" \
	--json \
	--expect-deepseek-v4-flash \
	--expect-file-size "$SIDECAR_EXPECT_FILE_SIZE" \
	--payload-sample-bytes "$PAYLOAD_SAMPLE_BYTES"
