#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_hf_api_report.sh <hf_repo> [--files|--files-oids|--top N|--top-oids N|--sum-gguf|--sum-safetensors]

Reports Hugging Face model-repo metadata (commit sha + file sizes) via the HF
HTTP API. This avoids cloning and avoids downloading any LFS blobs.

Arguments:
  hf_repo  Either:
             - org/name (example: deepseek-ai/DeepSeek-V4-Flash)
             - huggingface.co/org/name

Modes:
  (default)        Print a short summary + top 10 largest files.
  --files          Print "bytes<TAB>path<TAB>lfs|nolfs" for every file.
  --files-oids     Print "bytes<TAB>sha256<TAB>path<TAB>lfs|nolfs" for every file.
  --top N          Print only the top N largest files (default summary is 10).
  --top-oids N     Print top N as "bytes<TAB>sha256<TAB>path<TAB>lfs|nolfs".
  --sum-gguf       Print total bytes and GiB for *.gguf files.
  --sum-safetensors Print total bytes and GiB for *.safetensors files.

Notes:
  - This uses the "blobs=true" API parameter so per-file sizes are included.
  - If a large file is not marked as LFS, cloning would download it; this
    script flags such files in the summary.
EOF
}

if [ "${#}" -lt 1 ] || [ "${#}" -gt 3 ]; then
	usage >&2
	exit 2
fi

repo="$1"
shift || true

mode="summary"
top_n="10"
if [ "${#}" -gt 0 ]; then
	case "$1" in
		--files)
			mode="files"
			;;
		--files-oids)
			mode="files_oids"
			;;
		--top)
			mode="top"
			top_n="${2:-}"
			if [ -z "${top_n}" ] || ! [[ "${top_n}" =~ ^[0-9]+$ ]]; then
				echo "Invalid --top N" >&2
				exit 2
			fi
			;;
		--top-oids)
			mode="top_oids"
			top_n="${2:-}"
			if [ -z "${top_n}" ] || ! [[ "${top_n}" =~ ^[0-9]+$ ]]; then
				echo "Invalid --top-oids N" >&2
				exit 2
			fi
			;;
		--sum-gguf)
			mode="sum_gguf"
			;;
		--sum-safetensors)
			mode="sum_safetensors"
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
fi

if [[ "${repo}" == huggingface.co/* ]]; then
	repo="${repo#huggingface.co/}"
fi

api="https://huggingface.co/api/models/${repo}?blobs=true"
json="$(curl -sSfL "${api}")"

bytes_to_gib()
{
	awk -v b="$1" 'BEGIN { printf "%.2f", (b / 1024 / 1024 / 1024) }'
}

license="$(echo "${json}" | jq -r '
	.cardData.license
	// (.tags[]? | select(startswith("license:")) | split(":")[1])
	// "UNKNOWN"
	' | head -n 1)"
sha="$(echo "${json}" | jq -r '.sha // "UNKNOWN"')"
last_modified="$(echo "${json}" | jq -r '.lastModified // "UNKNOWN"')"
used_storage="$(echo "${json}" | jq -r '.usedStorage // 0')"
total_bytes="$(echo "${json}" | jq -r '[.siblings[].size] | add // 0')"
large_nolfs="$(echo "${json}" | jq -r '
	.siblings[]
	| select((.size // 0) >= (256*1024*1024) and (.lfs? == null))
	| .rfilename
	' | head -n 10 || true)"

sum_ext_bytes()
{
	local ext="$1"
	echo "${json}" | jq -r --arg ext "${ext}" '
		[ .siblings[]
		  | select(.rfilename | endswith($ext))
		  | .size
		] | add // 0
	'
}

print_top()
{
	local n="$1"
	echo "${json}" | jq -r --argjson n "${n}" '
		[ .siblings[] | { p: .rfilename, s: (.size // 0), l: (.lfs? != null) } ]
		| sort_by(.s) | reverse
		| .[0:$n]
		| .[]
		| "\(.s)\t\(.p)\t" + (if .l then "lfs" else "nolfs" end)
	'
}

print_top_oids()
{
	local n="$1"
	echo "${json}" | jq -r --argjson n "${n}" '
		[ .siblings[]
		  | { p: .rfilename, s: (.size // 0), l: (.lfs? != null), o: (.lfs.sha256 // "") }
		]
		| sort_by(.s) | reverse
		| .[0:$n]
		| .[]
		| "\(.s)\t\(.o)\t\(.p)\t" + (if .l then "lfs" else "nolfs" end)
	'
}

case "${mode}" in
	files)
		echo "${json}" | jq -r '
			.siblings[]
			| "\(.size // 0)\t\(.rfilename)\t" + (if (.lfs? != null) then "lfs" else "nolfs" end)
		'
		;;
	files_oids)
		echo "${json}" | jq -r '
			.siblings[]
			| "\(.size // 0)\t\(.lfs.sha256 // \"\")\t\(.rfilename)\t" + (if (.lfs? != null) then "lfs" else "nolfs" end)
		'
		;;
	top)
		print_top "${top_n}"
		;;
	top_oids)
		print_top_oids "${top_n}"
		;;
	sum_gguf)
		sum="$(sum_ext_bytes ".gguf")"
		printf "%s bytes (%.2f GiB)\n" "${sum}" "$(bytes_to_gib "${sum}")"
		;;
	sum_safetensors)
		sum="$(sum_ext_bytes ".safetensors")"
		printf "%s bytes (%.2f GiB)\n" "${sum}" "$(bytes_to_gib "${sum}")"
		;;
	summary)
		printf "repo:          %s\n" "${repo}"
		printf "sha:           %s\n" "${sha}"
		printf "license:       %s\n" "${license}"
		printf "last_modified: %s\n" "${last_modified}"
		printf "used_storage:  %s bytes (%.2f GiB)\n" "${used_storage}" "$(bytes_to_gib "${used_storage}")"
		printf "total_files:   %s bytes (%.2f GiB)\n" "${total_bytes}" "$(bytes_to_gib "${total_bytes}")"
		echo
		echo "top_files:"
		print_top "${top_n}"
		if [ -n "${large_nolfs}" ]; then
			echo
			echo "WARNING: large non-LFS blobs detected (cloning would download these):"
			echo "${large_nolfs}"
		fi
		;;
esac
