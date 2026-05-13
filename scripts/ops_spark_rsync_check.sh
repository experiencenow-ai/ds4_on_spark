#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_rsync_check.sh -- Mac-side rsync availability check (safe)

Usage:
  ops_spark_rsync_check.sh <spark0_user@host> <spark1_user@host> [spark2_user@host ...]
  ops_spark_rsync_check.sh --inventory-file <path>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Checks that `rsync` is installed on each target (required by ring-rsync workflows).
EOF
}

inventory_file=""

while [ $# -gt 0 ]; do
	case "$1" in
		--inventory-file)
			inventory_file="${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			break
			;;
	esac
done

if [ "$inventory_file" != "" ]; then
	if [ ! -f "$inventory_file" ]; then
		echo "inventory file not found: $inventory_file" >&2
		exit 2
	fi
	while IFS= read -r line || [ "$line" != "" ]; do
		case "$line" in
			""|\#*)
				continue
				;;
		esac
		set -- "$@" "$line"
	done < "$inventory_file"
fi

if [ "$#" -lt 1 ]; then
	usage >&2
	exit 2
fi

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd ssh

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

check_one()
{
	target="$1"
	if ssh $SSH_OPTS "$target" "command -v rsync >/dev/null 2>&1"; then
		ver="$(ssh $SSH_OPTS "$target" "rsync --version 2>/dev/null | sed -n '1p' || true" 2>/dev/null || true)"
		if [ "$ver" != "" ]; then
			echo "rsync_ok: $target ($ver)"
		else
			echo "rsync_ok: $target"
		fi
		return 0
	fi
	echo "rsync_missing: $target" >&2
	return 1
}

echo "== spark rsync check (Mac-side) =="
date -Is 2>/dev/null || date || true
missing=0
for t in "$@"; do
	if check_one "$t"; then
		:
	else
		missing=1
	fi
done

if [ "$missing" = "1" ]; then
	echo >&2
	echo "hint: the ring-rsync workflow requires rsync on Spark0 + all ring nodes." >&2
	echo "hint: use the ring-sim workflow (Spark0-local) if rsync is not available." >&2
	exit 2
fi

echo "== done =="

