#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_DIR="docs"
MAX_BYTES="${MAX_BYTES:-8388608}"

mkdir -p "$OUT_DIR"

refresh_one()
{
  local url="$1"
  local out="$2"
  local tmp
  tmp="$(mktemp)"

  python3 scripts/model_contract_inspect_quantized_artifact.py --url "$url" --max-bytes "$MAX_BYTES" --json >"$tmp"
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

# Pinned, metadata-only GGUF inspections (header + tensor table range reads only).
refresh_one \
  "https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF/resolve/6c6d74ce4efd3e1045c15e5823d75e62b6e4ba1d/DeepSeek-V4-Flash-Q4_K_M.gguf" \
  "$OUT_DIR/gguf-inspect-preyazz-6c6d74c-q4-k-m.json"

refresh_one \
  "https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF/resolve/0b34e0b629c706396002496e795e9f910f7bf69f/DeepSeek-V4-Flash-FP4-FP8-native.gguf" \
  "$OUT_DIR/gguf-inspect-nsparks-0b34e0b-fp4-fp8-native.json"

refresh_one \
  "https://huggingface.co/antirez/deepseek-v4-gguf/resolve/ef3b960827870d69ed0b225c095a617c12d7e80d/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf" \
  "$OUT_DIR/gguf-inspect-antirez-ef3b960-iq2xxs-chat-v2.json"

refresh_one \
  "https://huggingface.co/antirez/deepseek-v4-gguf/resolve/ef3b960827870d69ed0b225c095a617c12d7e80d/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf" \
  "$OUT_DIR/gguf-inspect-antirez-ef3b960-mtp-sidecar.json"

refresh_probe \
  "https://huggingface.co/antirez/deepseek-v4-gguf/resolve/ef3b960827870d69ed0b225c095a617c12d7e80d/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf" \
  "$OUT_DIR/mtp-sidecar-probe-antirez-ef3b960.json"

echo "OK: refreshed pinned DeepSeek V4 Flash GGUF inspections into $OUT_DIR (MAX_BYTES=$MAX_BYTES)"
