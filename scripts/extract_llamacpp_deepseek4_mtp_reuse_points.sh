#!/usr/bin/env sh
set -eu

# Extract “reuse points” in a DeepSeek V4 Flash llama.cpp fork for implementing
# DS4-style MTP draft using a deepseek4_mtp_support sidecar (mtp.0.* tensors).
#
# This script is read-only by default. It prints grep-able pointers (with line
# numbers) into the fork so patch authors can avoid “guessy” wiring.
#
# If LLAMA_DIR is missing, you may set ALLOW_FETCH=1 to clone the fork at the
# pinned commit, but this is optional and off by default.

LLAMA_DIR="${LLAMA_DIR:-$HOME/src/llama.cpp-deepseek-v4-flash-cuda-spark}"
LLAMA_REPO="${LLAMA_REPO:-https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git}"
LLAMA_COMMIT="${LLAMA_COMMIT:-9222e55}"
ALLOW_FETCH="${ALLOW_FETCH:-0}"

die()
{
	echo "$1" 1>&2
	exit 2
}

note()
{
	echo "$1"
}

if [ ! -d "$LLAMA_DIR" ]; then
	if [ "$ALLOW_FETCH" = "1" ]; then
		mkdir -p "$(dirname "$LLAMA_DIR")"
		git clone "$LLAMA_REPO" "$LLAMA_DIR"
	else
		die "missing LLAMA_DIR=$LLAMA_DIR (set ALLOW_FETCH=1 to clone $LLAMA_REPO)"
	fi
fi

if [ ! -d "$LLAMA_DIR/.git" ]; then
	die "LLAMA_DIR is not a git checkout: $LLAMA_DIR"
fi

rev="$(cd "$LLAMA_DIR" && git rev-parse HEAD 2>/dev/null || true)"
note "# llama.cpp DeepSeek4 MTP reuse-point extract"
note
note "- LLAMA_DIR: $LLAMA_DIR"
note "- LLAMA_REPO: $LLAMA_REPO"
note "- LLAMA_COMMIT (pin): $LLAMA_COMMIT"
note "- LLAMA_REV (current): ${rev:-unknown}"
note
if [ "$ALLOW_FETCH" = "1" ]; then
	(
		cd "$LLAMA_DIR"
		git fetch --all --tags || true
		git checkout "$LLAMA_COMMIT" || true
	) 1>/dev/null 2>/dev/null || true
	rev="$(cd "$LLAMA_DIR" && git rev-parse HEAD 2>/dev/null || true)"
	note "- LLAMA_REV (post-fetch/checkout best-effort): ${rev:-unknown}"
	note
fi

if [ ! -r "$LLAMA_DIR/src/models/deepseek4.cpp" ]; then
	die "missing file: $LLAMA_DIR/src/models/deepseek4.cpp"
fi
if [ ! -r "$LLAMA_DIR/src/llama-model.cpp" ]; then
	die "missing file: $LLAMA_DIR/src/llama-model.cpp"
fi
if [ ! -r "$LLAMA_DIR/src/llama-arch.cpp" ]; then
	die "missing file: $LLAMA_DIR/src/llama-arch.cpp"
fi

note "## NextN/MTP placeholders (model loader)"
note
rg -n "nextn_predict_layers|NextN/MTP|TODO: when MTP is implemented" "$LLAMA_DIR/src/llama-model.cpp" | head -n 120 || true
note
note "## NextN/MTP tensor naming (arch table)"
note
rg -n "NEXTN_|NextN/MTP tensors|nextn\\." "$LLAMA_DIR/src/llama-arch.cpp" | head -n 160 || true
note
note "## DeepSeek4 hyper-connection primitives (reuse for sidecar)"
note
rg -n "static dsv4_hc_mix dsv4_hc_pre\\(|static ggml_tensor \\* dsv4_hc_post\\(|static ggml_tensor \\* dsv4_hc_head\\(" "$LLAMA_DIR/src/models/deepseek4.cpp" || true
note
note "## DeepSeek4 attention path (compress_ratio == 0)"
note
rg -n "compress_ratio == 0\\)|build_attn_mha\\(|attn_sinks" "$LLAMA_DIR/src/models/deepseek4.cpp" | head -n 220 || true
note
note "## DeepSeek4 ffn path (MoE + shared expert)"
note
rg -n "build_moe_ffn\\(|ffn_gate_inp|ffn_(gate|up|down)_(exps|shexp)|exp_probs_b" "$LLAMA_DIR/src/models/deepseek4.cpp" | head -n 240 || true
note
note "## DeepSeek4 output head (HC head + norm + vocab projection)"
note
rg -n "output_hc_(fn|scale|base)|output_norm|ggml_mul_mat\\(ctx0, model\\.output" "$LLAMA_DIR/src/models/deepseek4.cpp" | head -n 80 || true

