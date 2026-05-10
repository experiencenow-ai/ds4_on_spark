#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_hf_smallest_gguf.sh <hf_repo> [--limit N] [--group-shards]

Print the smallest *.gguf files in a Hugging Face model repo using the HF HTTP
API (metadata only; no cloning and no LFS downloads).

Arguments:
  hf_repo     org/name (example: teamblobfish/DeepSeek-V4-Flash-GGUF)
              or huggingface.co/org/name

Options:
  --limit N   Number of rows to print (default: 10)
  --group-shards  Group sharded files and print summed sizes

Output columns:
  bytes<TAB>GiB<TAB>sha256<TAB>path<TAB>lfs|nolfs

When using --group-shards:
  total_bytes<TAB>GiB<TAB>shards<TAB>key
EOF
}

if [ "${#}" -lt 1 ]; then
	usage >&2
	exit 2
fi

repo="$1"
shift || true

limit="10"
group_shards="0"
if [ "${#}" -gt 0 ]; then
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
			--group-shards)
				group_shards="1"
				shift 1
				;;
			*)
				usage >&2
				exit 2
				;;
		esac
	done
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_REPORT="${ROOT_DIR}/scripts/upstream_hf_api_report.sh"

if [ "${group_shards}" = "1" ]; then
	"${API_REPORT}" "${repo}" --files-oids \
		| awk -F'\t' '
			$3 ~ /\.gguf$/ {
				bytes=$1;
				path=$3;
				key=path;
				sub(/-000[0-9]+-of-000[0-9]+\.gguf$/, ".gguf", key);
				sum[key]+=bytes;
				count[key]+=1;
			}
			END {
				for ( k in sum ) {
					printf "%d\t%.2f\t%d\t%s\n", sum[k], (sum[k]/1024/1024/1024), count[k], k;
				}
			}
		' \
		| sort -n -k1,1 \
		| head -n "${limit}"
	exit 0
fi

"${API_REPORT}" "${repo}" --files-oids \
	| awk -F'\t' '$3 ~ /\.gguf$/ { print $0 }' \
	| sort -n -k1,1 \
	| head -n "${limit}" \
	| awk -F'\t' '{
		bytes=$1; sha=$2; path=$3; lfs=$4;
		gib=(bytes/1024/1024/1024);
		printf "%s\t%.2f\t%s\t%s\t%s\n", bytes, gib, sha, path, lfs;
	}'
