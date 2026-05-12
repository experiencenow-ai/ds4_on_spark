#!/usr/bin/env bash
set -euo pipefail

# Pinned antirez sidecar (DeepSeek V4 Flash MTP) used as the contract reference for
# `general.architecture=deepseek4_mtp_support` + the compact 32-tensor `mtp.0.*` table.
#
# This script performs a metadata-only validation via HTTP range reads (no full model download).
#
# Override with:
#   SIDECAR_URL=... ./scripts/model_contract_probe_mtp_sidecar_antirez.sh

SIDECAR_URL="${SIDECAR_URL:-https://huggingface.co/antirez/deepseek-v4-gguf/resolve/b0c3326275d2207e25e42bc8ac0704952466b5bb/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf}"
SIDECAR_EXPECT_FILE_SIZE="${SIDECAR_EXPECT_FILE_SIZE:-3807602400}"
PAYLOAD_SAMPLE_BYTES="${PAYLOAD_SAMPLE_BYTES:-64}"
FINGERPRINT_GATE="${FINGERPRINT_GATE:-1}"

tmp_probe_json="$(mktemp "${TMPDIR:-/tmp}/ds4_mtp_sidecar_probe_antirez_XXXXXX.json")"
trap 'rm -f "$tmp_probe_json"' EXIT

set +e
python3 scripts/model_contract_probe_mtp_sidecar.py \
	--url "$SIDECAR_URL" \
	--json \
	--expect-deepseek-v4-flash \
	--expect-file-size "$SIDECAR_EXPECT_FILE_SIZE" \
	--payload-sample-bytes "$PAYLOAD_SAMPLE_BYTES" \
	>"$tmp_probe_json"
probe_status=$?
set -e

cat "$tmp_probe_json"

if [ "$FINGERPRINT_GATE" = "1" ] && [ "$PAYLOAD_SAMPLE_BYTES" != "0" ]; then
	echo "== payload fingerprint gate (pinned antirez reference) ==" 1>&2
	python3 scripts/verify_mtp_sidecar_payload_fingerprint.py --probe-json "$tmp_probe_json" --json 1>&2
fi

exit "$probe_status"
