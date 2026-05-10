#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

./scripts/model_contract_fetch_deepseek_v4_flash.sh >/dev/null
python3 scripts/model_contract_verify_deepseek_v4_flash.py >/dev/null

SUMMARY_PATH="fixtures/model_contract/deepseek_v4_flash/contract_summary.json"

echo "OK: DeepSeek V4 Flash contract refreshed + verified"
echo "Upstream:"
jq -r '.upstream | "  hf_repo_id=" + .hf_repo_id + " hf_revision=" + .hf_revision + " x_repo_commit=" + .x_repo_commit' "$SUMMARY_PATH"
echo "Topology:"
jq -r '.topology | "  n_layers=" + (.num_hidden_layers|tostring) + " hidden_size=" + (.hidden_size|tostring) + " n_heads=" + (.num_attention_heads|tostring) + " head_dim=" + (.head_dim|tostring) + " vocab_size=" + (.vocab_size|tostring)' "$SUMMARY_PATH"
echo "Attention schedule:"
jq -r '.attention_schedule | "  compress_ratios_len=" + (.compress_ratios|length|tostring) + " type_counts=" + (.type_counts|tojson)' "$SUMMARY_PATH"
echo "Checkpoint keyset:"
jq -r '.checkpoint_index | "  weight_map_num_tensors=" + (.weight_map_num_tensors|tostring) + " weight_map_keys_sha256=" + .weight_map_keys_sha256' "$SUMMARY_PATH"
echo "MTP:"
jq -r '.tensor_keys | "  mtp_present=" + (.mtp0.present|tostring) + " mtp_tensor_key_count=" + (.mtp0.tensor_key_count|tostring)' "$SUMMARY_PATH"
