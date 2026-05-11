#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="docs"
MAX_BYTES="${MAX_BYTES:-8388608}"

mkdir -p "$OUT_DIR"

PINNED_PREYAZZ_TRUNK_URL="https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF/resolve/6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d/DeepSeek-V4-Flash-Q4_K_M.gguf"
PINNED_NSPARKS_TRUNK_URL="https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF/resolve/0b34e0b629c706396002496e795e9f910f7bf69f/DeepSeek-V4-Flash-FP4-FP8-native.gguf"
PINNED_ANTIREZ_TRUNK_URL="https://huggingface.co/antirez/deepseek-v4-gguf/resolve/b0c3326275d2207e25e42bc8ac0704952466b5bb/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf"
PINNED_ANTIREZ_MTP_SIDECAR_URL="https://huggingface.co/antirez/deepseek-v4-gguf/resolve/b0c3326275d2207e25e42bc8ac0704952466b5bb/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf"

refresh_one()
{
  local url="$1"
  local out="$2"
  local tmp
  tmp="$(mktemp)"

  python3 scripts/model_contract_inspect_quantized_artifact.py --url "$url" --max-bytes "$MAX_BYTES" --json >"$tmp"
  mv "$tmp" "$out"
}

# Combined inspection (multiple URLs) is useful for trunk+sidecar artifact sets.
refresh_combined()
{
  local url1="$1"
  local url2="$2"
  local out="$3"
  local tmp
  tmp="$(mktemp)"

  python3 scripts/model_contract_inspect_quantized_artifact.py --url "$url1" --url "$url2" --max-bytes "$MAX_BYTES" --json >"$tmp"
  mv "$tmp" "$out"
}

refresh_probe()
{
  local url="$1"
  local out="$2"
  local tmp
  tmp="$(mktemp)"

  python3 scripts/model_contract_probe_mtp_sidecar.py --url "$url" --json --expect-deepseek-v4-flash >"$tmp"
  mv "$tmp" "$out"
}

refresh_probe_strong()
{
  local url="$1"
  local out="$2"
  local tmp
  tmp="$(mktemp)"

  python3 scripts/model_contract_probe_mtp_sidecar.py \
    --url "$url" \
    --json \
    --expect-deepseek-v4-flash \
    --expect-file-size 3807602400 \
    --payload-sample-bytes 64 >"$tmp"
  mv "$tmp" "$out"
}

# Pinned, metadata-only GGUF inspections (header + tensor table range reads only).
refresh_one \
  "$PINNED_PREYAZZ_TRUNK_URL" \
  "$OUT_DIR/gguf-inspect-preyazz-6c6d74c-q4-k-m.json"

refresh_one \
  "$PINNED_NSPARKS_TRUNK_URL" \
  "$OUT_DIR/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json"

refresh_one \
  "$PINNED_ANTIREZ_TRUNK_URL" \
  "$OUT_DIR/gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2.json"

refresh_one \
  "$PINNED_ANTIREZ_MTP_SIDECAR_URL" \
  "$OUT_DIR/gguf-inspect-antirez-b0c3326-mtp-sidecar.json"

# Combined trunk+sidecar view (artifact-set-level fingerprints + MTP trust signal).
refresh_combined \
  "$PINNED_ANTIREZ_TRUNK_URL" \
  "$PINNED_ANTIREZ_MTP_SIDECAR_URL" \
  "$OUT_DIR/gguf-inspect-antirez-b0c3326-iq2xxs-chat-v2-mtp-set.json"

refresh_probe \
  "$PINNED_ANTIREZ_MTP_SIDECAR_URL" \
  "$OUT_DIR/mtp-sidecar-probe-antirez-b0c3326.json"

refresh_probe_strong \
  "$PINNED_ANTIREZ_MTP_SIDECAR_URL" \
  "$OUT_DIR/mtp-sidecar-probe-antirez-b0c3326-payload64.json"

echo "OK: refreshed pinned DeepSeek V4 Flash GGUF inspections into $OUT_DIR (MAX_BYTES=$MAX_BYTES)"
