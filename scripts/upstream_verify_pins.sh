#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_MD="${ROOT_DIR}/docs/upstream-manifest.md"

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
	local upstream="$2"
	local url="$3"
	local ref="$4"
	local expected="$5"
	local got

	if [[ "${upstream}" == huggingface.co/* ]]; then
		if [ "${ref}" != "refs/heads/main" ] && [ "${ref}" != "refs/heads/master" ]; then
			echo "FAIL ${name}: unsupported HF ref: ${ref}" >&2
			return 1
		fi
		local report
		report="$("${ROOT_DIR}/scripts/upstream_hf_api_report.sh" "${upstream#huggingface.co/}")"
		got="$(awk '/^sha:/ {print $2}' <<<"${report}")"
		if [ -z "${got}" ] || [ "${got}" = "UNKNOWN" ]; then
			echo "FAIL ${name}: HF API did not return sha" >&2
			return 1
		fi
		if [ "${got}" != "${expected}" ]; then
			echo "FAIL ${name}: expected ${expected}, got ${got}" >&2
			return 1
		fi
		echo "OK   ${name}"
		return 0
	fi

	got="$(GIT_TERMINAL_PROMPT=0 git ls-remote "${url}" "${ref}" | awk '{print $1}' | head -n 1 || true)"
	if [ -z "${got}" ]; then
		echo "FAIL ${name}: ref not found: ${ref}" >&2
		return 1
	fi

	if [[ "${ref}" == refs/tags/* ]]; then
		# Annotated tags return the tag object hash unless dereferenced; always
		# prefer the dereferenced commit when available.
		local deref
		deref="$(GIT_TERMINAL_PROMPT=0 git ls-remote "${url}" "${ref}^{}" | awk '{print $1}' | head -n 1 || true)"
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

fail=0

while IFS=$'\t' read -r name upstream ref commit; do
	url="$(upstream_url "${upstream}")"
	check_ref "${name}" "${upstream}" "${url}" "${ref}" "${commit}" || fail=1
done < <(manifest_rows)

exit "${fail}"
