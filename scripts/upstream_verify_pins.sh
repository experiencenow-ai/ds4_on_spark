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
check_ref "vLLM" "https://github.com/vllm-project/vllm.git" "refs/tags/v0.20.2" "bc150f50299199599673614f80d12a196f377655" || fail=1
check_ref "Transformers" "https://github.com/huggingface/transformers.git" "refs/tags/v5.8.0" "a9e70365af64e028d40d8c7909deb7f138b49857" || fail=1
check_ref "llama.cpp" "https://github.com/ggml-org/llama.cpp.git" "refs/heads/master" "b46812de78f8fbcb6cf0154947e8633ebc78d9ac" || fail=1

exit "${fail}"
