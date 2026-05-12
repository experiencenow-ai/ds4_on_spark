#!/usr/bin/env sh
set -eu

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
ds4_c="$repo_root/upstreams/ds4/ds4.c"

ALLOW_FETCH="${ALLOW_FETCH:-0}"
if [ ! -r "$ds4_c" ]; then
	if [ "$ALLOW_FETCH" = "1" ]; then
		"$repo_root/scripts/fetch_upstreams.sh" ds4
	else
		echo "missing: $ds4_c" 1>&2
		echo "run: ./scripts/fetch_upstreams.sh ds4 (or set ALLOW_FETCH=1)" 1>&2
		exit 2
	fi
fi

echo "# ds4 MTP gamma=1 reference extract"
echo
echo "File: $ds4_c"
echo
echo "Key entrypoints (line numbers):"
rg -n "static void mtp_weights_bind\\(|static bool metal_graph_encode_output_head_mtp\\(|static bool metal_graph_eval_mtp_draft_from_hc\\(" "$ds4_c"
echo
echo "Operation-order hints (grep):"
rg -n "ds4_gpu_embed_token_hc_tensor\\(|ds4_gpu_rms_norm_weight_tensor\\(|ds4_gpu_matmul_q8_0_tensor\\(|ds4_gpu_repeat_hc_tensor\\(|ds4_gpu_rms_norm_weight_rows_tensor\\(|metal_graph_encode_decode_layer\\(|metal_graph_encode_output_head_mtp\\(" "$ds4_c" | head -n 120

