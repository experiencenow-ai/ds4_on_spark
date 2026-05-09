#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_ls_remote.sh

Prints the current commits for tracked upstreams (default-branch HEAD unless a ref is specified).
EOF
}

if [ "${#}" -ne 0 ]; then
	usage >&2
	exit 2
fi

print_ref()
{
	local name="$1"
	local url="$2"
	local ref="${3:-HEAD}"

	printf "== %s\n" "${name}"
	if [ "${ref}" = "HEAD" ]; then
		git ls-remote --symref "${url}" HEAD | sed -n '1,2p'
	else
		git ls-remote "${url}" "${ref}" | sed -n '1p'
	fi
	echo
}

print_ref "ds4" "https://github.com/antirez/ds4.git"
print_ref "DeepGEMM" "https://github.com/deepseek-ai/DeepGEMM.git"
print_ref "DeepSeek-V3" "https://github.com/deepseek-ai/DeepSeek-V3.git"
print_ref "DeepSeek-V4-Flash (HF)" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash"
print_ref "DeepSeek-V4-Flash-Base (HF)" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base"
print_ref "DeepSeek-V4-Flash GGUF (antirez, HF)" "https://huggingface.co/antirez/deepseek-v4-gguf"
print_ref "DeepSeek-V4-Flash GGUF (Preyazz, HF)" "https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF"
print_ref "DeepSeek-V4-Flash GGUF (BatiAI, HF)" "https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF"
print_ref "DeepSeek-V4-Flash GGUF (lovedheart, HF)" "https://huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF"
print_ref "DeepSeek-V4-Flash GGUF (nsparks, HF)" "https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF"
print_ref "DeepSeek-V4-Flash GGUF (cyberneurova, HF)" "https://huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF"
print_ref "vLLM" "https://github.com/vllm-project/vllm.git"
print_ref "Transformers" "https://github.com/huggingface/transformers.git"
print_ref "llama.cpp" "https://github.com/ggml-org/llama.cpp.git"
print_ref "llama.cpp (antirez V4 fork)" "https://github.com/antirez/llama.cpp-deepseek-v4-flash.git"
print_ref "llama.cpp (nisparks V4 WIP)" "https://github.com/nisparks/llama.cpp.git" "refs/heads/wip/deepseek-v4-support"
print_ref "llama.cpp (CUDA Spark fork)" "https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git"
print_ref "bati.cpp" "https://github.com/batiai/bati.cpp.git"
