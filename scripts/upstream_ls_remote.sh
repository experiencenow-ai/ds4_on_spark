#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_ls_remote.sh

Prints the default-branch HEAD commits for tracked upstreams.
EOF
}

if [ "${#}" -ne 0 ]; then
	usage >&2
	exit 2
fi

print_head()
{
	local name="$1"
	local url="$2"

	printf "== %s\n" "${name}"
	git ls-remote --symref "${url}" HEAD | sed -n '1,2p'
	echo
}

print_head "ds4" "https://github.com/antirez/ds4.git"
print_head "DeepGEMM" "https://github.com/deepseek-ai/DeepGEMM.git"
print_head "DeepSeek-V3" "https://github.com/deepseek-ai/DeepSeek-V3.git"
print_head "DeepSeek-V4-Flash (HF)" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash"
print_head "vLLM" "https://github.com/vllm-project/vllm.git"
print_head "Transformers" "https://github.com/huggingface/transformers.git"
print_head "llama.cpp" "https://github.com/ggml-org/llama.cpp.git"
