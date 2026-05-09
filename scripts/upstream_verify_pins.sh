#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_verify_pins.sh

Verifies that the pinned refs/commits in docs/upstream-manifest.md still resolve
upstream (without cloning).
EOF
}

if [ "${#}" -ne 0 ]; then
	usage >&2
	exit 2
fi

check_ref()
{
	local name="$1"
	local url="$2"
	local ref="$3"
	local expected="$4"
	local got

	got="$(git ls-remote "${url}" "${ref}" | awk '{print $1}' | head -n 1 || true)"
	if [ -z "${got}" ]; then
		echo "FAIL ${name}: ref not found: ${ref}" >&2
		return 1
	fi

	if [ "${got}" != "${expected}" ]; then
		# Annotated tags return the tag object hash unless dereferenced.
		local deref
		deref="$(git ls-remote "${url}" "${ref}^{}" | awk '{print $1}' | head -n 1 || true)"
		if [ -n "${deref}" ]; then
			got="${deref}"
		fi
	fi

	if [ "${got}" != "${expected}" ]; then
		echo "FAIL ${name}: expected ${expected}, got ${got}" >&2
		return 1
	fi

	echo "OK   ${name}"
	return 0
}

fail=0

check_ref "ds4" "https://github.com/antirez/ds4.git" "refs/heads/main" "d615ab08c8bce9b8242963ecece5aed6b5a79367" || fail=1
check_ref "DeepGEMM" "https://github.com/deepseek-ai/DeepGEMM.git" "refs/tags/v2.1.1.post3" "c9f8b34dcdacc20aa746b786f983492c51072870" || fail=1
check_ref "DeepSeek-V3" "https://github.com/deepseek-ai/DeepSeek-V3.git" "refs/tags/v1.0.0" "f6e34dd26772dd4a216be94a8899276c5dca9e43" || fail=1
check_ref "DeepSeek-V4-Flash (HF)" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash" "refs/heads/main" "6976c7ff1b30a1b2cb7805021b8ba4684041f136" || fail=1
check_ref "DeepSeek-V4-Flash-Base (HF)" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base" "refs/heads/main" "8855555deef230a27a21a8d6f294b7b7497759b6" || fail=1
check_ref "DeepSeek-V4-Flash GGUF (antirez, HF)" "https://huggingface.co/antirez/deepseek-v4-gguf" "refs/heads/main" "ef3b960827870d69ed0b225c095a617c12d7e80d" || fail=1
check_ref "DeepSeek-V4-Flash GGUF (nsparks, HF)" "https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF" "refs/heads/main" "0b34e0b629c706396002496e795e9f910f7bf69f" || fail=1
check_ref "DeepSeek-V4-Flash GGUF (cyberneurova, HF)" "https://huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF" "refs/heads/main" "665c8e035e2602d12d28b84920808b158f337e09" || fail=1
check_ref "vLLM" "https://github.com/vllm-project/vllm.git" "refs/tags/v0.20.2" "bc150f50299199599673614f80d12a196f377655" || fail=1
check_ref "Transformers" "https://github.com/huggingface/transformers.git" "refs/tags/v5.8.0" "a9e70365af64e028d40d8c7909deb7f138b49857" || fail=1
check_ref "llama.cpp" "https://github.com/ggml-org/llama.cpp.git" "refs/tags/b8833" "45cac7ca703fb9085eae62b9121fca01d20177f6" || fail=1
check_ref "llama.cpp (antirez V4 fork)" "https://github.com/antirez/llama.cpp-deepseek-v4-flash.git" "refs/heads/main" "2f2d44052b7d15c9c4dd6610f6e14a5f7b2d5f3f" || fail=1
check_ref "llama.cpp (nisparks V4 WIP)" "https://github.com/nisparks/llama.cpp.git" "refs/heads/wip/deepseek-v4-support" "9d364087024da141510267e6b269ee495ca45176" || fail=1
check_ref "llama.cpp (CUDA Spark fork)" "https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git" "refs/heads/master" "9222e55c13c965ccb7e9104fda58796edd84a732" || fail=1

exit "${fail}"
