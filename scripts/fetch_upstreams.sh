#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${ROOT_DIR}/upstreams"
MANIFEST_MD="${ROOT_DIR}/docs/upstream-manifest.md"

mkdir -p "${UPSTREAM_DIR}"

usage()
{
	cat <<'EOF'
Usage: ./scripts/fetch_upstreams.sh <name|all>

Clones pinned upstream refs into ./upstreams (ignored by git) and verifies the
checked-out commit matches docs/upstream-manifest.md.

Targets:
  ds4
  deepgemm
  flashmla
  deepseek_v3
  deepseek_v4_flash_hf   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_flash_base_hf  (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_antirez   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_preyazz   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_batiai    (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_lovedheart  (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_nsparks   (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_cyberneurova  (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  deepseek_v4_gguf_teamblobfish  (HF metadata only; uses GIT_LFS_SKIP_SMUDGE=1)
  bati_cpp   (runtime required by batiai/DeepSeek-V4-Flash-GGUF)
  vllm
  transformers
  llama_cpp
  llama_cpp_deepseek_v4_flash
  llama_cpp_deepseek_v4_support_wip
  llama_cpp_deepseek_v4_port_cchuter
  llama_cpp_cuda_spark
  spark_v4_bringup_mockingjay
  spark_v4_bringup_bigs
  spark_v4_gb10_runtime_devid791
  deepseek_v4_flash_sm120_patch
  all
EOF
}

manifest_commit_for()
{
	local upstream="$1"
	local ref="$2"

	awk -v want_upstream="${upstream}" -v want_ref="${ref}" '
	BEGIN { t=0 }
	/^\| Name \| Upstream \| Ref \| Commit \|/ { t=1; next }
	{
		if ( t == 0 ) next
		if ( $0 !~ /^\|/ ) exit
		if ( $0 ~ /^\| ---/ ) next
		line = $0
		sub(/^\|/, "", line)
		sub(/\|[[:space:]]*$/, "", line)
		n = split(line, a, "|")
		for ( i=1; i<=4; i++ ) {
			gsub(/`/, "", a[i])
			gsub(/^[[:space:]]+|[[:space:]]+$/, "", a[i])
		}
		if ( a[2] == want_upstream && a[3] == want_ref ) {
			print a[4]
			exit 0
		}
	}
	' "${MANIFEST_MD}" || true
}

verify_pinned_checkout()
{
	local name="$1"
	local dest="$2"
	local expected="$3"
	local got

	if [ -z "${expected}" ]; then
		echo "FAIL ${name}: missing manifest pin for checkout" >&2
		echo "  manifest: ${MANIFEST_MD}" >&2
		return 1
	fi

	got="$(cd "${dest}" && git rev-parse HEAD)"
	if [ "${got}" != "${expected}" ]; then
		echo "FAIL ${name}: pinned commit mismatch after fetch" >&2
		echo "  expected: ${expected}" >&2
		echo "  got:      ${got}" >&2
		echo "  hint: run ./scripts/upstream_verify_pins.sh and update docs/upstream-manifest.md if pins drifted" >&2
		return 1
	fi

	return 0
}

clone_or_update()
{
	local name="$1"
	local url="$2"
	local ref="$3"
	local expected="$4"
	local dest="${UPSTREAM_DIR}/${name}"

	if [ -d "${dest}/.git" ]; then
		( cd "${dest}" && git fetch --depth 1 origin "${ref}" && git checkout -q FETCH_HEAD )
		verify_pinned_checkout "${name}" "${dest}" "${expected}"
		return $?
	fi

	git clone --depth 1 --branch "${ref}" "${url}" "${dest}" >/dev/null 2>&1 || {
		# Some refs are tags/refs that don't work with --branch on older git; fall back to init+fetch.
		mkdir -p "${dest}"
		( cd "${dest}" && git init -q && git remote add origin "${url}" && git fetch --depth 1 origin "${ref}" && git checkout -q FETCH_HEAD )
	}
	verify_pinned_checkout "${name}" "${dest}" "${expected}"
	return $?
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
	local expected="$4"
	local dest="${UPSTREAM_DIR}/${name}"

	if [ -d "${dest}/.git" ]; then
		( cd "${dest}" && git_nolfs fetch --depth 1 origin "${ref}" && git_nolfs checkout -q FETCH_HEAD )
		verify_pinned_checkout "${name}" "${dest}" "${expected}"
		return $?
	fi

	# Avoid downloading large LFS weights and avoid git-lfs crashes by fully disabling LFS filters.
	( export GIT_LFS_SKIP_SMUDGE=1; git_nolfs clone --depth 1 --branch "${ref}" "${url}" "${dest}" >/dev/null 2>&1 ) || {
		mkdir -p "${dest}"
		( cd "${dest}" && git_nolfs init -q && git_nolfs remote add origin "${url}" && git_nolfs fetch --depth 1 origin "${ref}" && git_nolfs checkout -q FETCH_HEAD )
	}
	verify_pinned_checkout "${name}" "${dest}" "${expected}"
	return $?
}

fetch_one()
{
	local target="$1"
	local upstream ref expected

	case "${target}" in
		ds4)
			upstream="antirez/ds4"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "ds4" "https://github.com/antirez/ds4.git" "${ref}" "${expected}"
			;;
		deepgemm)
			upstream="deepseek-ai/DeepGEMM"; ref="refs/tags/v2.1.1.post3"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "deepgemm" "https://github.com/deepseek-ai/DeepGEMM.git" "${ref}" "${expected}"
			;;
		flashmla)
			upstream="deepseek-ai/FlashMLA"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "flashmla" "https://github.com/deepseek-ai/FlashMLA.git" "${ref}" "${expected}"
			;;
		deepseek_v3)
			upstream="deepseek-ai/DeepSeek-V3"; ref="refs/tags/v1.0.0"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "deepseek_v3" "https://github.com/deepseek-ai/DeepSeek-V3.git" "${ref}" "${expected}"
			;;
		deepseek_v4_flash_hf)
			# HF metadata/config only: do not download weights.
			upstream="huggingface.co/deepseek-ai/DeepSeek-V4-Flash"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_flash_hf" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash" "${ref}" "${expected}"
			;;
		deepseek_v4_flash_base_hf)
			# HF metadata/config only: do not download weights.
			upstream="huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_flash_base_hf" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base" "${ref}" "${expected}"
			;;
		deepseek_v4_gguf_antirez)
			upstream="huggingface.co/antirez/deepseek-v4-gguf"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_gguf_antirez" "https://huggingface.co/antirez/deepseek-v4-gguf" "${ref}" "${expected}"
			;;
		deepseek_v4_gguf_preyazz)
			upstream="huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_gguf_preyazz" "https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF" "${ref}" "${expected}"
			;;
		deepseek_v4_gguf_batiai)
			upstream="huggingface.co/batiai/DeepSeek-V4-Flash-GGUF"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_gguf_batiai" "https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF" "${ref}" "${expected}"
			;;
		deepseek_v4_gguf_lovedheart)
			upstream="huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_gguf_lovedheart" "https://huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF" "${ref}" "${expected}"
			;;
		deepseek_v4_gguf_nsparks)
			upstream="huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_gguf_nsparks" "https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF" "${ref}" "${expected}"
			;;
		deepseek_v4_gguf_cyberneurova)
			upstream="huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_gguf_cyberneurova" "https://huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF" "${ref}" "${expected}"
			;;
		deepseek_v4_gguf_teamblobfish)
			upstream="huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update_nolfs "deepseek_v4_gguf_teamblobfish" "https://huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF" "${ref}" "${expected}"
			;;
		bati_cpp)
			upstream="batiai/bati.cpp"; ref="refs/tags/v0.1.2"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "bati_cpp" "https://github.com/batiai/bati.cpp.git" "${ref}" "${expected}"
			;;
		vllm)
			upstream="vllm-project/vllm"; ref="refs/tags/v0.20.2"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "vllm" "https://github.com/vllm-project/vllm.git" "${ref}" "${expected}"
			;;
		transformers)
			upstream="huggingface/transformers"; ref="refs/tags/v5.8.0"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "transformers" "https://github.com/huggingface/transformers.git" "${ref}" "${expected}"
			;;
		llama_cpp)
			upstream="ggml-org/llama.cpp"; ref="refs/tags/b9085"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "llama_cpp" "https://github.com/ggml-org/llama.cpp.git" "${ref}" "${expected}"
			;;
		llama_cpp_deepseek_v4_flash)
			upstream="antirez/llama.cpp-deepseek-v4-flash"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "llama_cpp_deepseek_v4_flash" "https://github.com/antirez/llama.cpp-deepseek-v4-flash.git" "${ref}" "${expected}"
			;;
		llama_cpp_deepseek_v4_support_wip)
			upstream="nisparks/llama.cpp"; ref="refs/heads/wip/deepseek-v4-support"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "llama_cpp_deepseek_v4_support_wip" "https://github.com/nisparks/llama.cpp.git" "${ref}" "${expected}"
			;;
		llama_cpp_deepseek_v4_port_cchuter)
			upstream="cchuter/llama.cpp"; ref="refs/heads/feat/v4-port"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "llama_cpp_deepseek_v4_port_cchuter" "https://github.com/cchuter/llama.cpp.git" "${ref}" "${expected}"
			;;
		llama_cpp_cuda_spark)
			upstream="kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark"; ref="refs/heads/master"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "llama_cpp_cuda_spark" "https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git" "${ref}" "${expected}"
			;;
		spark_v4_bringup_mockingjay)
			upstream="Mockingjay1316/deepseek-v4-flash-spark"; ref="refs/heads/master"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "spark_v4_bringup_mockingjay" "https://github.com/Mockingjay1316/deepseek-v4-flash-spark.git" "${ref}" "${expected}"
			;;
		spark_v4_bringup_bigs)
			upstream="bigs/deepseek-v4-flash-dgx-spark"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "spark_v4_bringup_bigs" "https://github.com/bigs/deepseek-v4-flash-dgx-spark.git" "${ref}" "${expected}"
			;;
		spark_v4_gb10_runtime_devid791)
			upstream="devid791/dsv4-flash-gb10-runtime"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "spark_v4_gb10_runtime_devid791" "https://github.com/devid791/dsv4-flash-gb10-runtime.git" "${ref}" "${expected}"
			;;
		deepseek_v4_flash_sm120_patch)
			upstream="0xSero/deepseek-v4-flash-sm120"; ref="refs/heads/main"; expected="$(manifest_commit_for "${upstream}" "${ref}")"
			clone_or_update "deepseek_v4_flash_sm120_patch" "https://github.com/0xSero/deepseek-v4-flash-sm120.git" "${ref}" "${expected}"
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
		fetch_one flashmla
		fetch_one deepseek_v3
		fetch_one deepseek_v4_flash_hf
		fetch_one deepseek_v4_flash_base_hf
		fetch_one deepseek_v4_gguf_antirez
		fetch_one deepseek_v4_gguf_preyazz
		fetch_one deepseek_v4_gguf_batiai
		fetch_one deepseek_v4_gguf_lovedheart
		fetch_one deepseek_v4_gguf_nsparks
		fetch_one deepseek_v4_gguf_cyberneurova
		fetch_one deepseek_v4_gguf_teamblobfish
		fetch_one bati_cpp
		fetch_one vllm
		fetch_one transformers
		fetch_one llama_cpp
		fetch_one llama_cpp_deepseek_v4_flash
		fetch_one llama_cpp_deepseek_v4_support_wip
		fetch_one llama_cpp_deepseek_v4_port_cchuter
		fetch_one llama_cpp_cuda_spark
		fetch_one spark_v4_bringup_mockingjay
		fetch_one spark_v4_bringup_bigs
		fetch_one spark_v4_gb10_runtime_devid791
		fetch_one deepseek_v4_flash_sm120_patch
		echo "Fetched: ${UPSTREAM_DIR}"
		return 0
	fi

	fetch_one "$1"
	echo "Fetched: ${UPSTREAM_DIR}/$1"
}

main "$@"
