#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${ROOT_DIR}/upstreams"

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_hf_pointer_report.sh <target|path>

Print a report of Git LFS pointer metadata in a metadata-only Hugging Face clone
(sizes + sha256 oids) without downloading the large blobs.

Examples:
  ./scripts/fetch_upstreams.sh deepseek_v4_gguf_preyazz
  ./scripts/upstream_hf_pointer_report.sh deepseek_v4_gguf_preyazz

  ./scripts/upstream_hf_pointer_report.sh ./upstreams/deepseek_v4_flash_hf
EOF
}

if [ "${#}" -ne 1 ]; then
	usage >&2
	exit 2
fi

arg="$1"
dir="$arg"

if [ ! -d "${dir}" ] && [ -d "${UPSTREAM_DIR}/${arg}" ]; then
	dir="${UPSTREAM_DIR}/${arg}"
fi

if [ ! -d "${dir}" ]; then
	echo "Not a directory: ${dir}" >&2
	exit 2
fi

relpath()
{
	local p="$1"
	if [[ "${p}" == "${dir}/"* ]]; then
		printf "%s" "${p#${dir}/}"
		return 0
	fi
	printf "%s" "${p}"
}

is_lfs_pointer()
{
	local f="$1"
	local first

	first="$(head -n 1 "${f}" 2>/dev/null || true)"
	[ "${first}" = "version https://git-lfs.github.com/spec/v1" ]
}

report_one()
{
	local f="$1"
	local oid size gib

	oid="$(awk '/^oid sha256:/{print $2}' "${f}" | head -n 1 | sed 's/^sha256://')"
	size="$(awk '/^size /{print $2}' "${f}" | head -n 1)"
	if [ -z "${oid}" ] || [ -z "${size}" ]; then
		return 0
	fi

	gib="$(awk -v s="${size}" 'BEGIN{printf "%.1f", (s/(1024*1024*1024))}')"
	printf "%12s  %6s GiB  %s  %s\n" "${size}" "${gib}" "${oid}" "$(relpath "${f}")"
}

tmp="${ROOT_DIR}/.gitlocal_hf_pointer_report.$$"
trap 'rm -f "${tmp}"' EXIT

find "${dir}" -type f -not -path '*/.git/*' -print0 \
	| xargs -0 -I{} bash -c 'f="$1"; shift; if head -n 1 "$f" 2>/dev/null | grep -qx "version https://git-lfs.github.com/spec/v1"; then printf "%s\n" "$f"; fi' _ {} \
	> "${tmp}" || true

if [ ! -s "${tmp}" ]; then
	echo "No Git LFS pointer files found under: ${dir}" >&2
	exit 1
fi

while IFS= read -r f; do
	report_one "${f}"
done < "${tmp}" | sort -k1,1nr
