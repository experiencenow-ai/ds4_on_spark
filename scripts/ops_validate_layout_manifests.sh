#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_validate_layout_manifests.sh -- validate deploy layout manifest TSVs (safe)

Usage:
  ops_validate_layout_manifests.sh

Notes:
  - Non-destructive; intended to run from the repo root (Mac-side).
  - Validates `deploy/layout/*/*.manifest.tsv`:
    - expected TSV columns (src, dst, mode, owner:group, notes)
    - src paths exist in-repo and are repo-relative
    - mode + owner:group are well-formed
    - basic destination path sanity (system vs user manifests)
EOF
}

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$root"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
	usage
	exit 0
fi

need_file()
{
	path="$1"
	if [ ! -f "$path" ]; then
		echo "missing: $path" >&2
		exit 2
	fi
}

err=0

check_manifest()
{
	manifest="$1"
	mode="$2" # system|user

	need_file "$manifest"

	echo "== validate $manifest =="

	awk -v manifest="$manifest" -v mode="$mode" '
function fail(msg) { printf("%s:%d: %s\n", manifest, NR, msg) > "/dev/stderr"; exit(2); }
BEGIN { FS="\t"; OFS="\t"; }
{
	line=$0
	if (line ~ /^[[:space:]]*$/) next
	if (line ~ /^[[:space:]]*#/) next
	if (NF != 5) fail("expected 5 TSV columns; got " NF)
	src=$1
	dst=$2
	fmode=$3
	owner=$4
	notes=$5
	if (src ~ /^\//) fail("src must be repo-relative (no leading /): " src)
	if (src ~ /(^|\/)\.\.(\/|$)/) fail("src must not contain .. segments: " src)
	if (src ~ /[[:space:]]/) fail("src must not contain whitespace: " src)
	if (dst == "") fail("dst must not be empty")
	if (fmode !~ /^[0-7]{4}$/) fail("mode must be 4 octal digits (e.g. 0644): " fmode)
	if (owner !~ /^[a-z_][a-z0-9_-]*:[a-z_][a-z0-9_-]*$/) fail("owner:group must look like name:name: " owner)
	if (notes == "") fail("notes must not be empty")
	if (mode == "system")
	{
		if (dst !~ /^\//) fail("system dst must be absolute (/...): " dst)
		if (dst ~ /\$HOME/) fail("system dst must not reference $HOME: " dst)
	}
	else if (mode == "user")
	{
		if (dst !~ /^\$HOME\//) fail("user dst must start with $HOME/: " dst)
		if (dst ~ /^\/etc\//) fail("user dst must not land under /etc/: " dst)
		if (dst ~ /^\/opt\//) fail("user dst must not land under /opt/: " dst)
	}
}
' "$manifest" || err=1

	while IFS= read -r line || [ "$line" != "" ]; do
		case "$line" in
			""|\#*)
				continue
				;;
		esac
		src="$(printf "%s" "$line" | awk -F '\t' '{print $1}')"
		if [ ! -f "$src" ]; then
			echo "$manifest: missing src file: $src" >&2
			err=1
		fi
	done < "$manifest"
}

check_manifest "deploy/layout/spark012/system.manifest.tsv" "system"
check_manifest "deploy/layout/spark012/user.manifest.tsv" "user"

if [ "$err" -ne 0 ] 2>/dev/null; then
	exit 2
fi

echo "== ok =="

