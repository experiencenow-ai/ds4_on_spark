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
echo "Tokenizer:"
jq -r '.tokenizer | "  bos_id=" + (.bos_token_id|tostring) + " eos_id=" + (.eos_token_id|tostring) + " add_bos=" + (.add_bos_token|tostring) + " add_eos=" + (.add_eos_token|tostring) + " pad_is_eos=" + (.pad_token_is_eos|tostring) + " model_max_length=" + (.model_max_length|tostring)' "$SUMMARY_PATH"
echo "Attention schedule:"
jq -r '.attention_schedule | "  compress_ratios_len=" + (.compress_ratios|length|tostring) + " type_counts=" + (.type_counts|tojson)' "$SUMMARY_PATH"
echo "Cache:"
jq -r '.cache | "  window_size=" + (.window_size|tostring) + " topk_mask_value=" + (.topk_mask_value|tostring) + " kv_cache_shape=" + .kv_cache_shape' "$SUMMARY_PATH"
jq -r '.cache.kv_cache_sizes_at_reference_defaults | "  ref_defaults: max_seq_len=" + (.max_seq_len|tostring) + " max_batch_size=" + (.max_batch_size|tostring) + " kv_cache_size_by_ratio=" + (.kv_cache_size_by_compress_ratio|tojson)' "$SUMMARY_PATH"
echo "MoE:"
jq -r '.moe | "  routed_experts=" + (.n_routed_experts|tostring) + " shared_experts=" + (.n_shared_experts|tostring) + " activated_experts=" + (.n_activated_experts|tostring) + " hash_layers=" + (.n_hash_layers|tostring) + " inter_dim=" + (.moe_inter_dim|tostring) + " scoring=" + (.scoring_func|tostring) + " route_scale=" + (.route_scale|tostring)' "$SUMMARY_PATH"
echo "Quantization (Flash runtime semantics):"
jq -r '.quantization.inference_config | "  expert_dtype=" + (.expert_dtype|tostring) + " scale_fmt=" + (.scale_fmt|tostring)' "$SUMMARY_PATH"
jq -r '.quantization.linear_tensor_contract | "  fp8_block_size=" + (.fp8.block_size|tostring) + " fp8_scale_dtype=" + (.fp8.scale_dtype|tostring) + " fp4_block_size=" + (.fp4.fp4_block_size|tostring) + " fp4_scale_dtype=" + (.fp4.scale_dtype|tostring)' "$SUMMARY_PATH"
echo "Checkpoint keyset:"
jq -r '.checkpoint_index | "  weight_map_num_tensors=" + (.weight_map_num_tensors|tostring) + " weight_map_keys_sha256=" + .weight_map_keys_sha256' "$SUMMARY_PATH"
jq -r '.checkpoint_index.weight_map_prefix_fingerprints as $p | "  prefix_fingerprints.prefixes=" + ($p|keys|sort|join(",")) + " mtp.keys_sha256=" + ($p.mtp.keys_sha256 // "n/a")' "$SUMMARY_PATH"
echo "MTP:"
jq -r '.mtp | "  n_mtp_layers=" + (.n_mtp_layers|tostring) + " namespace_prefix=" + .namespace_prefix + " compress_ratio_rule=" + .compress_ratio_rule' "$SUMMARY_PATH"
jq -r '.tensor_keys | "  mtp_present=" + (.mtp0.present|tostring) + " mtp_tensor_key_count=" + (.mtp0.tensor_key_count|tostring)' "$SUMMARY_PATH"
echo "Oracles:"
jq -r '.oracle.encoding_oracle | "  encoding_oracle_required=" + (.required|tostring) + " fixtures=" + .fixtures_glob + " verifier=" + .verifier' "$SUMMARY_PATH"
jq -r '.oracle.logits_oracle | "  logits_oracle_weights_required=" + (.weights_required|tostring) + " prompts=" + .prompts_fixture + " generator=" + .generator' "$SUMMARY_PATH"
jq -r '.oracle.mtp | "  mtp_oracle_weights_required=" + (.weights_required|tostring) + " generator_hint=" + .generator_hint' "$SUMMARY_PATH"
