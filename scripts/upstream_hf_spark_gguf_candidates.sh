#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_hf_spark_gguf_candidates.sh <query> [--limit N] [--sort <downloads|likes|lastModified>] [--max-gib X] [--require-base-model SUBSTR]

Searches Hugging Face model repos by query, then (metadata-only) inspects each
hit via the HF HTTP API to find the *smallest* GGUF artifact group (shards are
summed). Prints a TSV report filtered to candidates <= --max-gib.

Notes:
  - No weights are downloaded: this uses only https://huggingface.co/api/models
  - GGUF shard groups are detected by the suffix pattern:
      -00001-of-00023.gguf  =>  .gguf (key)
  - --require-base-model filters by the model card "base_model" field, which is
    often a string or list; it is normalized to a comma-separated string.

Examples:
  ./scripts/upstream_hf_spark_gguf_candidates.sh "DeepSeek-V4-Flash GGUF" --limit 50 --sort downloads --max-gib 110
  ./scripts/upstream_hf_spark_gguf_candidates.sh "DeepSeek-V4-Flash GGUF" --limit 50 --sort downloads --max-gib 110 --require-base-model deepseek-ai/DeepSeek-V4-Flash
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
max_gib="110"
require_base_model=""

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
		--max-gib)
			max_gib="${2:-}"
			if [ -z "${max_gib}" ] || ! [[ "${max_gib}" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
				echo "Invalid --max-gib X" >&2
				exit 2
			fi
			shift 2
			;;
		--require-base-model)
			require_base_model="${2:-}"
			if [ -z "${require_base_model}" ]; then
				echo "Invalid --require-base-model SUBSTR" >&2
				exit 2
			fi
			shift 2
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

bytes_to_gib()
{
	awk -v b="$1" 'BEGIN { printf "%.2f", (b / 1024 / 1024 / 1024) }'
}

license_from_json()
{
	jq -r '
		.cardData.license
		// (.tags[]? | select(startswith("license:")) | split(":")[1])
		// "UNKNOWN"
	' | head -n 1
}

base_model_from_json()
{
	jq -r '
		def norm_bm:
			if . == null then
				""
			elif (type == "string") then
				.
			elif (type == "array") then
				(map(
					if (type == "string") then
						.
					elif (type == "object") then
						(.id? // .modelId? // .repo? // .name? // "")
					else
						""
					end
				) | map(select(. != "")) | join(", "))
			elif (type == "object") then
				(.id? // .modelId? // .repo? // .name? // "")
			else
				""
			end;
		(.cardData.base_model?) as $bm
		| if ($bm != null) and ($bm | tostring) != "" then
			($bm | norm_bm)
		  else
			(.cardData.base_models? | norm_bm)
		  end
	' | head -n 1
}

smallest_grouped_gguf()
{
	jq -r '
		[
			.siblings[]?
			| select((.rfilename // "") | endswith(".gguf"))
			| { p: .rfilename, s: (.size // 0) }
			| . as $f
			| {
				key: (
					($f.p
						| sub("([.]gguf)?-000[0-9]+-of-000[0-9]+[.]gguf$"; ".gguf")
					)
				),
				s: $f.s
			}
		]
		| group_by(.key)
		| map({ key: .[0].key, bytes: (map(.s) | add // 0), shards: length })
		| sort_by(.bytes)
		| (.[0]? // empty)
		| [ (.bytes|tostring), (.shards|tostring), .key ]
		| @tsv
	'
}

printf "modelId\tsha\tlastModified\tdownloads\tlikes\tlicense\tbase_model\tsmallest_gguf_bytes\tsmallest_gguf_gib\tsmallest_gguf_shards\tsmallest_gguf_key\n"

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
	base_model="$(echo "${info_json}" | base_model_from_json)"
	if [ -n "${require_base_model}" ]; then
		if ! echo "${base_model}" | rg -q --fixed-strings "${require_base_model}"; then
			continue
		fi
	fi
	smallest="$(echo "${info_json}" | smallest_grouped_gguf || true)"
	[ -n "${smallest}" ] || continue
	gguf_bytes="$(echo "${smallest}" | awk -F'\t' '{print $1}')"
	gguf_shards="$(echo "${smallest}" | awk -F'\t' '{print $2}')"
	gguf_key="$(echo "${smallest}" | awk -F'\t' '{print $3}')"
	gguf_gib="$(bytes_to_gib "${gguf_bytes}")"
	if awk -v v="${gguf_gib}" -v m="${max_gib}" 'BEGIN { exit(!(v <= m)) }'; then
		printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
			"${model_id}" "${sha}" "${last_modified}" "${downloads}" "${likes}" "${license}" "${base_model}" \
			"${gguf_bytes}" "${gguf_gib}" "${gguf_shards}" "${gguf_key}"
	fi
done
