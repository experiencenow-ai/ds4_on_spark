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
start_line="$(rg -n "static bool metal_graph_eval_mtp_draft_from_hc\\(" "$ds4_c" | head -n 1 | cut -d: -f1 || true)"
if [ "$start_line" != "" ]; then
	echo "## gamma=1 draft call sequence (ds4 source excerpt)"
	echo
	echo "This excerpt is intended as a no-guessy implementation checklist for external runtimes:"
	echo '- build `mtp_input_hc` from trunk embed + `prev_hc` using `enorm/e_proj/hnorm/h_proj`'
	echo "- run 1 decode layer against a **separate** MTP raw-cache frontier"
	echo '- run the MTP output head (`hc_head_*` + `norm`) + trunk vocab projection'
	echo
	# Print a fixed-size window; the function is stable-sized in the pinned DS4 commit.
	end_line="$((start_line + 220))"
	sed -n "${start_line},${end_line}p" "$ds4_c" | nl -ba -v "$start_line" | rg "ds4_metal_begin_commands\\(|ds4_metal_embed_token_hc_tensor\\(|ds4_metal_rms_norm_weight_tensor\\(|ds4_metal_matmul_q8_0_tensor\\(|ds4_metal_repeat_hc_tensor\\(|ds4_metal_rms_norm_weight_rows_tensor\\(|ds4_metal_add_tensor\\(|metal_graph_encode_decode_layer\\(|metal_graph_encode_output_head_mtp\\(|ds4_metal_indexer_topk_tensor\\(|ds4_metal_end_commands\\(" || true
	echo
	echo "## raw-cache frontier bookkeeping (ds4 source excerpt)"
	echo
	sed -n "${start_line},${end_line}p" "$ds4_c" | nl -ba -v "$start_line" | rg "raw_row =|n_raw =|mtp_n_raw|raw_window|raw_cap" || true
	echo
fi

echo "## Operation-order hints (global grep; first matches)"
rg -n "ds4_metal_embed_token_hc_tensor\\(|ds4_metal_rms_norm_weight_tensor\\(|ds4_metal_matmul_q8_0_tensor\\(|ds4_metal_repeat_hc_tensor\\(|ds4_metal_rms_norm_weight_rows_tensor\\(|metal_graph_encode_decode_layer\\(|metal_graph_encode_output_head_mtp\\(" "$ds4_c" | head -n 120
