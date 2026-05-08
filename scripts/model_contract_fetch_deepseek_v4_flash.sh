#!/usr/bin/env bash
set -euo pipefail

REPO_ID="deepseek-ai/DeepSeek-V4-Flash"
REV="main"
OUT_DIR="fixtures/model_contract/deepseek_v4_flash"

FILES=(
  "config.json"
  "generation_config.json"
  "model.safetensors.index.json"
  "tokenizer.json"
  "tokenizer_config.json"
  "encoding/README.md"
  "encoding/encoding_dsv4.py"
  "encoding/test_encoding_dsv4.py"
  "encoding/tests/test_input_1.json"
  "encoding/tests/test_input_2.json"
  "encoding/tests/test_input_3.json"
  "encoding/tests/test_input_4.json"
  "encoding/tests/test_output_1.txt"
  "encoding/tests/test_output_2.txt"
  "encoding/tests/test_output_3.txt"
  "encoding/tests/test_output_4.txt"
  "inference/README.md"
  "inference/config.json"
  "inference/convert.py"
  "inference/generate.py"
  "inference/kernel.py"
  "inference/model.py"
  "inference/requirements.txt"
)

hf_url()
{
  local path="$1"
  printf "https://huggingface.co/%s/resolve/%s/%s" "$REPO_ID" "$REV" "$path"
}

fetch_one()
{
  local path="$1"
  local url
  url="$(hf_url "$path")"

  if [[ "$path" == *.safetensors ]] || [[ "$path" == *"model-"*"-of-"*".safetensors" ]]; then
    echo "Refusing to download checkpoint shard: $path" 1>&2
    return 2
  fi

  mkdir -p "$OUT_DIR/$(dirname "$path")"
  curl -LfsS "$url" -o "$OUT_DIR/$path"
}

mkdir -p "$OUT_DIR"

# Record the upstream commit hash as seen by Hugging Face for this revision.
UPSTREAM_COMMIT="$(curl -sSI "$(hf_url "config.json")" | awk -F': ' 'tolower($1)=="x-repo-commit"{print $2}' | tr -d '\r' | tail -n 1)"
if [[ -n "$UPSTREAM_COMMIT" ]]; then
  printf "%s\n" "$UPSTREAM_COMMIT" > "$OUT_DIR/upstream_commit.txt"
fi

for f in "${FILES[@]}"; do
  fetch_one "$f"
done

echo "OK: fetched $((${#FILES[@]})) files into $OUT_DIR"

