#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${ROOT_DIR}/upstreams"

mkdir -p "${UPSTREAM_DIR}"

usage()
{
	cat <<'EOF'
Usage: ./scripts/fetch_upstreams.sh <name|all>

Clones pinned upstream refs into ./upstreams (ignored by git).

Targets:
  ds4
  deepgemm
  deepseek_v3
  deepseek_v4_flash_hf   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_flash_base_hf  (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_antirez   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_preyazz   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_batiai    (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_nsparks   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_cyberneurova  (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  bati_cpp   (runtime required by batiai/DeepSeek-V4-Flash-GGUF)
  vllm
  transformers
  llama_cpp
  llama_cpp_deepseek_v4_flash
  llama_cpp_deepseek_v4_support_wip
  llama_cpp_cuda_spark
  all
EOF
}

clone_or_update()
{
	local name="$1"
	local url="$2"
	local ref="$3"
	local dest="${UPSTREAM_DIR}/${name}"

	if [ -d "${dest}/.git" ]; then
		( cd "${dest}" && git fetch --depth 1 origin "${ref}" && git checkout -q FETCH_HEAD )
		return 0
	fi

	git clone --depth 1 --branch "${ref}" "${url}" "${dest}" >/dev/null 2>&1 || {
		# Some refs are tags/refs that don't work with --branch on older git; fall back to init+fetch.
		mkdir -p "${dest}"
		( cd "${dest}" && git init -q && git remote add origin "${url}" && git fetch --depth 1 origin "${ref}" && git checkout -q FETCH_HEAD )
	}
}

git_nolfs()
{
	git \
		-c filter.lfs.smudge= \
		-c filter.lfs.process= \
		-c filter.lfs.required=false \
		"$@"
}

clone_or_update_nolfs()
{
	local name="$1"
	local url="$2"
	local ref="$3"
	local dest="${UPSTREAM_DIR}/${name}"

	if [ -d "${dest}/.git" ]; then
		( cd "${dest}" && git_nolfs fetch --depth 1 origin "${ref}" && git_nolfs checkout -q FETCH_HEAD )
		return 0
	fi

	# Avoid downloading large LFS weights and avoid git-lfs crashes by fully disabling LFS filters.
	( export GIT_LFS_SKIP_SMUDGE=1; git_nolfs clone --depth 1 --branch "${ref}" "${url}" "${dest}" >/dev/null 2>&1 ) || {
		mkdir -p "${dest}"
		( cd "${dest}" && git_nolfs init -q && git_nolfs remote add origin "${url}" && git_nolfs fetch --depth 1 origin "${ref}" && git_nolfs checkout -q FETCH_HEAD )
	}
}

fetch_one()
{
	local target="$1"

	case "${target}" in
		ds4)
			clone_or_update "ds4" "https://github.com/antirez/ds4.git" "refs/heads/main"
			;;
		deepgemm)
			clone_or_update "deepgemm" "https://github.com/deepseek-ai/DeepGEMM.git" "refs/tags/v2.1.1.post3"
			;;
		deepseek_v3)
			clone_or_update "deepseek_v3" "https://github.com/deepseek-ai/DeepSeek-V3.git" "refs/tags/v1.0.0"
			;;
		deepseek_v4_flash_hf)
			# HF metadata/config only: do not download weights.
			clone_or_update_nolfs "deepseek_v4_flash_hf" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash" "refs/heads/main"
			;;
		deepseek_v4_flash_base_hf)
			# HF metadata/config only: do not download weights.
			clone_or_update_nolfs "deepseek_v4_flash_base_hf" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base" "refs/heads/main"
			;;
		deepseek_v4_gguf_antirez)
			clone_or_update_nolfs "deepseek_v4_gguf_antirez" "https://huggingface.co/antirez/deepseek-v4-gguf" "refs/heads/main"
			;;
		deepseek_v4_gguf_preyazz)
			clone_or_update_nolfs "deepseek_v4_gguf_preyazz" "https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF" "refs/heads/main"
			;;
		deepseek_v4_gguf_batiai)
			clone_or_update_nolfs "deepseek_v4_gguf_batiai" "https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF" "refs/heads/main"
			;;
		deepseek_v4_gguf_nsparks)
			clone_or_update_nolfs "deepseek_v4_gguf_nsparks" "https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF" "refs/heads/main"
			;;
		deepseek_v4_gguf_cyberneurova)
			clone_or_update_nolfs "deepseek_v4_gguf_cyberneurova" "https://huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF" "refs/heads/main"
			;;
		bati_cpp)
			clone_or_update "bati_cpp" "https://github.com/batiai/bati.cpp.git" "refs/tags/v0.1.2"
			;;
		vllm)
			clone_or_update "vllm" "https://github.com/vllm-project/vllm.git" "refs/tags/v0.20.2"
			;;
		transformers)
			clone_or_update "transformers" "https://github.com/huggingface/transformers.git" "refs/tags/v5.8.0"
			;;
		llama_cpp)
			clone_or_update "llama_cpp" "https://github.com/ggml-org/llama.cpp.git" "refs/tags/b8833"
			;;
		llama_cpp_deepseek_v4_flash)
			clone_or_update "llama_cpp_deepseek_v4_flash" "https://github.com/antirez/llama.cpp-deepseek-v4-flash.git" "refs/heads/main"
			;;
		llama_cpp_deepseek_v4_support_wip)
			clone_or_update "llama_cpp_deepseek_v4_support_wip" "https://github.com/nisparks/llama.cpp.git" "refs/heads/wip/deepseek-v4-support"
			;;
		llama_cpp_cuda_spark)
			clone_or_update "llama_cpp_cuda_spark" "https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git" "refs/heads/master"
			;;
		*)
			echo "Unknown target: ${target}" >&2
			usage >&2
			return 2
			;;
	esac
}

main()
{
	if [ "${#}" -ne 1 ]; then
		usage >&2
		return 2
	fi

	if [ "$1" = "all" ]; then
		fetch_one ds4
		fetch_one deepgemm
		fetch_one deepseek_v3
		fetch_one deepseek_v4_flash_hf
		fetch_one deepseek_v4_flash_base_hf
		fetch_one deepseek_v4_gguf_antirez
		fetch_one deepseek_v4_gguf_preyazz
		fetch_one deepseek_v4_gguf_batiai
		fetch_one deepseek_v4_gguf_nsparks
		fetch_one deepseek_v4_gguf_cyberneurova
		fetch_one bati_cpp
		fetch_one vllm
		fetch_one transformers
		fetch_one llama_cpp
		fetch_one llama_cpp_deepseek_v4_flash
		fetch_one llama_cpp_deepseek_v4_support_wip
		fetch_one llama_cpp_cuda_spark
		echo "Fetched: ${UPSTREAM_DIR}"
		return 0
	fi

	fetch_one "$1"
	echo "Fetched: ${UPSTREAM_DIR}/$1"
}

main "$@"
