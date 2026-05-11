#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST_MD="${ROOT_DIR}/docs/upstream-manifest.md"
LS_REMOTE_TIMEOUT_SEC="${UPSTREAM_LS_REMOTE_TIMEOUT_SEC:-20}"

usage()
{
	cat <<'EOF'
Usage: ./scripts/upstream_verify_pins.sh [--quiet] [--summary]

Verifies that the pinned refs/commits in docs/upstream-manifest.md still resolve
upstream (without cloning).

Options:
  --quiet    Only print failures (suppresses per-row OK lines).
  --summary  Print a final OK/FAIL count summary.
  -h, --help Show this help.

Environment:
  UPSTREAM_LS_REMOTE_TIMEOUT_SEC  Per-upstream `git ls-remote` timeout (default: 20).
EOF
}

quiet=0
summary=0

while [ "${#}" -gt 0 ]; do
	case "$1" in
		--quiet)
			quiet=1
			;;
		--summary)
			summary=1
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
	shift
done

check_ref()
{
	local name="$1"
	local upstream="$2"
	local url="$3"
	local ref="$4"
	local expected="$5"
	local got

	if [[ "${upstream}" == huggingface.co/* ]]; then
		if [ "${ref}" = "refs/heads/main" ] || [ "${ref}" = "refs/heads/master" ]; then
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
			if [ "${quiet}" -eq 0 ]; then
				echo "OK   ${name}"
			fi
			return 0
		fi
		# For non-default refs (e.g. HF PR refs), use the git transport.
	fi

	local out
	out="$(GIT_TERMINAL_PROMPT=0 timeout "${LS_REMOTE_TIMEOUT_SEC}s" git ls-remote "${url}" "${ref}" 2>/dev/null || true)"
	got="$(awk '{print $1}' <<<"${out}" | head -n 1 || true)"
	if [ -z "${got}" ]; then
		echo "FAIL ${name}: ls-remote timed out or ref missing: ${ref}" >&2
		return 1
	fi

	if [[ "${ref}" == refs/tags/* ]]; then
		# Annotated tags return the tag object hash unless dereferenced; always
		# prefer the dereferenced commit when available.
		local deref
		out="$(GIT_TERMINAL_PROMPT=0 timeout "${LS_REMOTE_TIMEOUT_SEC}s" git ls-remote "${url}" "${ref}^{}" 2>/dev/null || true)"
		deref="$(awk '{print $1}' <<<"${out}" | head -n 1 || true)"
		if [ -n "${deref}" ]; then
			got="${deref}"
		fi
	fi

	if [ "${got}" != "${expected}" ]; then
		echo "FAIL ${name}: expected ${expected}, got ${got}" >&2
		return 1
	fi

	if [ "${quiet}" -eq 0 ]; then
		echo "OK   ${name}"
	fi
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
ok_count=0
fail_count=0

while IFS=$'\t' read -r name upstream ref commit; do
	url="$(upstream_url "${upstream}")"
	if check_ref "${name}" "${upstream}" "${url}" "${ref}" "${commit}"; then
		ok_count=$((ok_count + 1))
	else
		fail=1
		fail_count=$((fail_count + 1))
	fi
done < <(manifest_rows)

if [ "${summary}" -ne 0 ]; then
	echo "SUMMARY ok=${ok_count} fail=${fail_count}"
fi

exit "${fail}"
