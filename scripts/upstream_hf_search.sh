#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_hf_search.sh <query> [--limit N] [--sort <downloads|likes|lastModified>] [--fast]

Searches Hugging Face model repos via the HF HTTP API and prints a TSV list:

  modelId<TAB>sha<TAB>lastModified<TAB>downloads<TAB>likes<TAB>license

Notes:
  - This does not download weights; it only queries metadata endpoints.
  - By default, this script resolves `sha` and `lastModified` via the per-repo
    `/api/models/<id>` endpoint because the search index can be stale for some
    repos. Use `--fast` to skip per-repo resolution (best-effort only).
  - Follow up with ./scripts/upstream_hf_api_report.sh <modelId> to inspect
    per-file sizes (including LFS sha256) and to sum *.gguf / *.safetensors.

Examples:
  ./scripts/upstream_hf_search.sh "DeepSeek-V4-Flash GGUF" --sort downloads --limit 25
  ./scripts/upstream_hf_search.sh "DeepSeek V4 Flash" --sort lastModified --limit 50 | rg -i 'gguf'
EOF
}

if [ "${#}" -lt 1 ]; then
	usage >&2
	exit 2
fi

query="$1"
shift || true

limit="20"
sort="downloads"
fast="0"

while [ "${#}" -gt 0 ]; do
	case "$1" in
		--limit)
			limit="${2:-}"
			if [ -z "${limit}" ] || ! [[ "${limit}" =~ ^[0-9]+$ ]]; then
				echo "Invalid --limit N" >&2
				exit 2
			fi
			shift 2
			;;
		--sort)
			sort="${2:-}"
			case "${sort}" in
				downloads|likes|lastModified)
					;;
				*)
					echo "Invalid --sort value: ${sort}" >&2
					exit 2
					;;
			esac
			shift 2
			;;
		--fast)
			fast="1"
			shift 1
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			usage >&2
			exit 2
			;;
	esac
done

enc_query="$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "${query}")"

api="https://huggingface.co/api/models?search=${enc_query}&limit=${limit}&sort=${sort}&direction=-1&full=true"
search_json="$(curl -sSfL "${api}")"

license_from_json()
{
	jq -r '
		.cardData.license
		// (.tags[]? | select(startswith("license:")) | split(":")[1])
		// "UNKNOWN"
	' | head -n 1
}

if [ "${fast}" = "1" ]; then
	echo "${search_json}" | jq -r '
		.[]?
		| . as $m
		| {
			modelId: ($m.modelId // ""),
			sha: ($m.sha // ""),
			lastModified: ($m.lastModified // ""),
			downloads: ($m.downloads // 0),
			likes: ($m.likes // 0),
			license: (
				($m.cardData.license? // "") as $l
				| if $l != "" then
					$l
				  else
					( first($m.tags[]? | select(startswith("license:")) | split(":")[1]) // "UNKNOWN" )
				  end
			)
		}
		| [ .modelId, .sha, .lastModified, (.downloads|tostring), (.likes|tostring), .license ]
		| @tsv
	'
	exit 0
fi

echo "${search_json}" | jq -r '
	.[]?
	| [ (.modelId // ""), ((.downloads // 0) | tostring), ((.likes // 0) | tostring) ]
	| @tsv
' | while IFS=$'\t' read -r model_id downloads likes; do
	[ -n "${model_id}" ] || continue
	info_json="$(curl -sSfL "https://huggingface.co/api/models/${model_id}?blobs=true")"
	sha="$(echo "${info_json}" | jq -r '.sha // ""')"
	last_modified="$(echo "${info_json}" | jq -r '.lastModified // ""')"
	license="$(echo "${info_json}" | license_from_json)"
	printf "%s\t%s\t%s\t%s\t%s\t%s\n" "${model_id}" "${sha}" "${last_modified}" "${downloads}" "${likes}" "${license}"
done
