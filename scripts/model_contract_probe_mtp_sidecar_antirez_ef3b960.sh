#!/usr/bin/env bash
set -euo pipefail

# Pinned antirez sidecar (DeepSeek V4 Flash MTP) used as the contract reference for
# `general.architecture=deepseek4_mtp_support` + the compact 32-tensor `mtp.0.*` table.
#
# This script performs a metadata-only validation via HTTP range reads (no full model download).
#
# Override with:
#   SIDECAR_URL=... ./scripts/model_contract_probe_mtp_sidecar_antirez_ef3b960.sh

SIDECAR_URL="${SIDECAR_URL:-https://huggingface.co/antirez/deepseek-v4-gguf/resolve/ef3b960827870d69ed0b225c095a617c12d7e80d/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf}"

python3 scripts/model_contract_probe_mtp_sidecar.py --url "$SIDECAR_URL" --json --expect-deepseek-v4-flash
