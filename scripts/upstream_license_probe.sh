#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_MD="${ROOT_DIR}/docs/upstream.md"

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_license_probe.sh

Checks whether each pinned upstream has an in-repo license file at the pinned
commit (without cloning).

Notes:
  - This only checks for common file names (LICENSE/COPYING/NOTICE). It does not
    determine the *actual* license text meaningfully; it is a presence probe.
  - For Hugging Face repos, licenses are often declared in the model card
    (`README.md`) instead of a standalone `LICENSE` file. For non-UNKNOWN HF
    entries, this probe accepts `README.md` as the “license carrier”.
  - For HF rows whose declared license is UNKNOWN, this probe still reports
    whether `README.md` is reachable so a human can inspect it for license text.
EOF
}

if [ "${#}" -ne 0 ]; then
	usage >&2
	exit 2
fi

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
		for ( i=1; i<=5; i++ ) {
			gsub(/`/, "", a[i])
			gsub(/^[[:space:]]+|[[:space:]]+$/, "", a[i])
		}
		if ( a[1] == "" || a[2] == "" || a[4] == "" ) next
		print a[1] "\t" a[2] "\t" a[4] "\t" a[5]
	}
	' "${MANIFEST_MD}"
}

license_url()
{
	local upstream="$1"
	local commit="$2"
	local path="$3"

	if [[ "${upstream}" == huggingface.co/* ]]; then
		printf "https://%s/raw/%s/%s" "${upstream}" "${commit}" "${path}"
		return 0
	fi

	printf "https://raw.githubusercontent.com/%s/%s/%s" "${upstream}" "${commit}" "${path}"
	return 0
}

probe_one()
{
	local url
	url="$(license_url "$1" "$2" "$3")"
	curl -fsS -m 10 -o /dev/null "${url}" 2>/dev/null
}

hf_declared_license()
{
	local upstream="$1"
	local report
	report="$("${ROOT_DIR}/scripts/upstream_hf_api_report.sh" "${upstream#huggingface.co/}")"
	awk '/^license:/ {print $2}' <<<"${report}"
}

hf_readme_present()
{
	local upstream="$1"
	local commit="$2"

	if probe_one "${upstream}" "${commit}" "README.md"; then
		return 0
	fi
	return 1
}

LICENSE_PATHS=(
	"LICENSE"
	"LICENSE.txt"
	"LICENSE.md"
	"LICENSE-CODE"
	"LICENSE-MODEL"
	"COPYING"
	"COPYING.txt"
	"NOTICE"
)

fail=0

while IFS=$'\t' read -r name upstream commit declared; do
	found=""
	for p in "${LICENSE_PATHS[@]}"; do
		if probe_one "${upstream}" "${commit}" "${p}"; then
			found="${p}"
			break
		fi
	done

	if [ -n "${found}" ]; then
		printf "OK   %s\t%s\t%s\t%s\n" "${name}" "${upstream}" "${commit}" "${found}"
	else
		if [[ "${upstream}" == huggingface.co/* ]]; then
			readme_present="0"
			if hf_readme_present "${upstream}" "${commit}"; then
				readme_present="1"
			fi

			api_license="$(hf_declared_license "${upstream}" || true)"
			if [ -n "${api_license}" ] && [ "${api_license}" != "UNKNOWN" ]; then
				printf "OK   %s\t%s\t%s\t%s\n" "${name}" "${upstream}" "${commit}" "HF_API_LICENSE:${api_license}"
				continue
			fi

			if [ "${readme_present}" = "1" ] && [[ "${declared:-UNKNOWN}" != UNKNOWN* ]]; then
				printf "OK   %s\t%s\t%s\t%s\n" "${name}" "${upstream}" "${commit}" "README.md"
				continue
			fi

			if [ "${readme_present}" = "1" ]; then
				printf "MISS %s\t%s\t%s\t%s\n" "${name}" "${upstream}" "${commit}" "${declared:-UNKNOWN} (README.md present)"
			else
				printf "MISS %s\t%s\t%s\t%s\n" "${name}" "${upstream}" "${commit}" "${declared:-UNKNOWN}"
			fi
		else
			printf "MISS %s\t%s\t%s\t%s\n" "${name}" "${upstream}" "${commit}" "${declared:-UNKNOWN}"
		fi
		case "${declared:-UNKNOWN}" in
			UNKNOWN*|"DeepSeek (link)")
				;;
			*)
				fail=1
				;;
		esac
	fi
done < <(manifest_rows)

exit "${fail}"
