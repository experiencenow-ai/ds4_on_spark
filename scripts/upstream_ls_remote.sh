#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_ls_remote.sh [--head|--pinned|--all]

Modes:
  --head    Print default-branch HEAD for a curated list (legacy behavior).
  --pinned  Print the current resolution of refs pinned in docs/upstream-manifest.md.
  --all     Print both reports (HEAD first, then pinned).

Default is --head for backwards compatibility.
EOF
}

mode="head"
if [ "${#}" -gt 1 ]; then
	usage >&2
	exit 2
fi
if [ "${#}" -eq 1 ]; then
	case "$1" in
		--head)
			mode="head"
			;;
		--pinned)
			mode="pinned"
			;;
		--all)
			mode="all"
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
fi

print_ref()
{
	local name="$1"
	local url="$2"
	local ref="${3:-HEAD}"

	printf "== %s\n" "${name}"
	if [[ "${url}" == https://huggingface.co/* ]]; then
		local repo sha
		repo="${url#https://huggingface.co/}"
		local report
		report="$("${ROOT_DIR}/scripts/upstream_hf_api_report.sh" "${repo}")"
		sha="$(awk '/^sha:/ {print $2}' <<<"${report}")"
		if [ -z "${sha}" ] || [ "${sha}" = "UNKNOWN" ]; then
			printf "ref: (hf api) UNKNOWN\n\n"
			return 0
		fi
		if [ "${ref}" = "HEAD" ]; then
			printf "ref: refs/heads/main\tHEAD\n"
			printf "%s\tHEAD\n\n" "${sha}"
			return 0
		fi
		printf "%s\t%s\n\n" "${sha}" "${ref}"
		return 0
	fi
	if [ "${ref}" = "HEAD" ]; then
		GIT_TERMINAL_PROMPT=0 git ls-remote --symref "${url}" HEAD | sed -n '1,2p'
	else
		GIT_TERMINAL_PROMPT=0 git ls-remote "${url}" "${ref}" | sed -n '1p'
	fi
	echo
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_MD="${ROOT_DIR}/docs/upstream-manifest.md"

manifest_rows()
{
	awk '
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
		if ( a[1] == "" || a[2] == "" || a[3] == "" || a[4] == "" ) next
		print a[1] "\t" a[2] "\t" a[3] "\t" a[4]
	}
	' "${MANIFEST_MD}"
}

upstream_url()
{
	local upstream="$1"

	if [[ "${upstream}" == huggingface.co/* ]]; then
		printf "https://%s" "${upstream}"
		return 0
	fi

	printf "https://github.com/%s.git" "${upstream}"
	return 0
}

print_pinned()
{
	local name="$1"
	local upstream="$2"
	local url="$3"
	local ref="$4"
	local expected="$5"
	local got

	if [[ "${upstream}" == huggingface.co/* ]]; then
		if [ "${ref}" != "refs/heads/main" ] && [ "${ref}" != "refs/heads/master" ]; then
			printf "== %s\n" "${name}"
			printf "upstream:  %s\n" "${upstream}"
			printf "ref:       %s\n" "${ref}"
			printf "expected:  %s\n" "${expected}"
			printf "got:       UNSUPPORTED_HF_REF\n\n"
			return 0
		fi
		local report
		report="$("${ROOT_DIR}/scripts/upstream_hf_api_report.sh" "${upstream#huggingface.co/}")"
		got="$(awk '/^sha:/ {print $2}' <<<"${report}")"
		printf "== %s\n" "${name}"
		printf "upstream:  %s\n" "${upstream}"
		printf "ref:       %s\n" "${ref}"
		printf "expected:  %s\n" "${expected}"
		printf "got:       %s\n\n" "${got:-MISSING}"
		return 0
	fi

	got="$(GIT_TERMINAL_PROMPT=0 git ls-remote "${url}" "${ref}" | awk '{print $1}' | head -n 1 || true)"
	if [ -z "${got}" ]; then
		printf "== %s\n" "${name}"
		printf "upstream:  %s\n" "${upstream}"
		printf "ref:       %s\n" "${ref}"
		printf "expected:  %s\n" "${expected}"
		printf "got:       MISSING\n\n"
		return 0
	fi

	if [[ "${ref}" == refs/tags/* ]]; then
		local deref
		deref="$(GIT_TERMINAL_PROMPT=0 git ls-remote "${url}" "${ref}^{}" | awk '{print $1}' | head -n 1 || true)"
		if [ -n "${deref}" ]; then
			got="${deref}"
		fi
	fi

	printf "== %s\n" "${name}"
	printf "upstream:  %s\n" "${upstream}"
	printf "ref:       %s\n" "${ref}"
	printf "expected:  %s\n" "${expected}"
	printf "got:       %s\n\n" "${got}"
}

print_head_report()
{
	print_ref "ds4" "https://github.com/antirez/ds4.git"
	print_ref "DeepGEMM" "https://github.com/deepseek-ai/DeepGEMM.git"
	print_ref "FlashMLA" "https://github.com/deepseek-ai/FlashMLA.git"
	print_ref "DeepSeek-V3" "https://github.com/deepseek-ai/DeepSeek-V3.git"
	print_ref "DeepSeek-V4-Flash (HF)" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash"
	print_ref "DeepSeek-V4-Flash-Base (HF)" "https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash-Base"
	print_ref "DeepSeek-V4-Flash GGUF (antirez, HF)" "https://huggingface.co/antirez/deepseek-v4-gguf"
	print_ref "DeepSeek-V4-Flash GGUF (ssweens, HF)" "https://huggingface.co/ssweens/DeepSeek-V4-Flash-GGUF-YMMV"
	print_ref "DeepSeek-V4-Flash GGUF (Preyazz, HF)" "https://huggingface.co/Preyazz/DeepSeek-V4-Flash-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (BatiAI, HF)" "https://huggingface.co/batiai/DeepSeek-V4-Flash-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (lovedheart, HF)" "https://huggingface.co/lovedheart/DeepSeek-V4-Flash-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (nsparks, HF)" "https://huggingface.co/nsparks/DeepSeek-V4-Flash-FP4-FP8-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (cyberneurova, HF)" "https://huggingface.co/cyberneurova/CyberNeurova-DeepSeek-V4-Flash-abliterated-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (teamblobfish, HF)" "https://huggingface.co/teamblobfish/DeepSeek-V4-Flash-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (asidaddy, HF)" "https://huggingface.co/asidaddy/Deepseek-V4-Flash-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (Volko76, HF)" "https://huggingface.co/Volko76/DeepSeek-V4-Flash-GGUF"
	print_ref "DeepSeek-V4-Flash GGUF (setar007, HF)" "https://huggingface.co/setar007/DeepSeek-V4-Flash-Q8xQ5-GGUF"
	print_ref "vLLM" "https://github.com/vllm-project/vllm.git"
	print_ref "Transformers" "https://github.com/huggingface/transformers.git"
	print_ref "SGLang" "https://github.com/sgl-project/sglang.git"
	print_ref "llama.cpp" "https://github.com/ggml-org/llama.cpp.git"
	print_ref "llama.cpp (antirez V4 fork)" "https://github.com/antirez/llama.cpp-deepseek-v4-flash.git"
	print_ref "llama.cpp (nisparks V4 WIP)" "https://github.com/nisparks/llama.cpp.git" "refs/heads/wip/deepseek-v4-support"
	print_ref "llama.cpp (cchuter V4 port)" "https://github.com/cchuter/llama.cpp.git" "refs/heads/feat/v4-port"
	print_ref "llama.cpp (ssweens V4 fork)" "https://github.com/ssweens/llama.cpp-deepseek-v4.git" "refs/heads/main"
	print_ref "llama.cpp (CUDA Spark fork)" "https://github.com/kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark.git"
	print_ref "bati.cpp" "https://github.com/batiai/bati.cpp.git"
	print_ref "Spark bring-up (pruned checkpoint)" "https://github.com/Mockingjay1316/deepseek-v4-flash-spark.git"
	print_ref "Spark bring-up (native checkpoint runtime)" "https://github.com/bigs/deepseek-v4-flash-dgx-spark.git"
	print_ref "Spark bring-up (GB10 C++ runtime, MXFP4)" "https://github.com/devid791/dsv4-flash-gb10-runtime.git"
	print_ref "Blackwell/SGLang arch patch (reference)" "https://github.com/0xSero/deepseek-v4-flash-sm120.git"
}

print_pinned_report()
{
	while IFS=$'\t' read -r name upstream ref commit; do
		url="$(upstream_url "${upstream}")"
		print_pinned "${name}" "${upstream}" "${url}" "${ref}" "${commit}"
	done < <(manifest_rows)
}

case "${mode}" in
	head)
		print_head_report
		;;
	pinned)
		print_pinned_report
		;;
	all)
		print_head_report
		print_pinned_report
		;;
esac
