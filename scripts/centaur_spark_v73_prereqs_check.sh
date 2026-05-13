#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
centaur_spark_v73_prereqs_check.sh -- Centaur v73 prereq check (Mac-side, safe)

Usage:
  centaur_spark_v73_prereqs_check.sh <spark_user@host> [spark_user@host ...]
  centaur_spark_v73_prereqs_check.sh --inventory-file <path>
  centaur_spark_v73_prereqs_check.sh [--check-rsync] <spark_user@host> [spark_user@host ...]

Environment:
  SSH_OPTS      Optional ssh options override.
  CHECK_RSYNC   Set to 1 to also check for rsync on each target.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Checks Centaur v73 prerequisites needed for staging + node setup:
      python3, python3 -m venv (venv module), unzip
  - Optional: checks rsync for ring-rsync workflows (spark0-orchestrated).
EOF
}

inventory_file=""
check_rsync="${CHECK_RSYNC:-0}"

while [ $# -gt 0 ]; do
	case "$1" in
		--inventory-file)
			inventory_file="${2:-}"
			shift 2
			;;
		--check-rsync)
			check_rsync=1
			shift
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

	if ! ssh $SSH_OPTS "$target" "true" >/dev/null 2>&1; then
		echo "ssh_failed: $target" >&2
		return 1
	fi

	remote='
set -eu
missing=0

if command -v python3 >/dev/null 2>&1; then
	python3 -V 2>&1 | sed -E "s/^/python3: /"
else
	echo "python3: MISSING" >&2
	missing=1
fi

if command -v python3 >/dev/null 2>&1; then
	if python3 -c "import venv" >/dev/null 2>&1; then
		echo "venv: ok"
	else
		echo "venv: MISSING (python3 -m venv unavailable; install python3-venv)" >&2
		missing=1
	fi
fi

if command -v unzip >/dev/null 2>&1; then
	unzip -v 2>/dev/null | sed -n "1p" | sed -E "s/^/unzip: /" || echo "unzip: ok"
else
	echo "unzip: MISSING" >&2
	missing=1
fi

if [ "${1:-0}" = "1" ]; then
	if command -v rsync >/dev/null 2>&1; then
		rsync --version 2>/dev/null | sed -n "1p" | sed -E "s/^/rsync: /" || echo "rsync: ok"
	else
		echo "rsync: MISSING (required for ring-rsync workflows)" >&2
		missing=1
	fi
fi

exit "$missing"
'

	echo "== centaur v73 prereqs ($target) =="
	if ssh $SSH_OPTS "$target" "sh -s -- \"$check_rsync\"" <<EOF
$remote
EOF
	then
		echo "prereqs_ok: $target"
		return 0
	fi
	echo "prereqs_missing: $target" >&2
	return 1
}

echo "== centaur v73 prereq check (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "check_rsync=$check_rsync"
echo

err=0
for t in "$@"; do
	if check_one "$t"; then
		:
	else
		err=1
	fi
	echo
done

if [ "$err" -ne 0 ]; then
	echo "hint: Centaur v73 node setup requires python3 + venv module + unzip." >&2
	echo "hint: ring-rsync also requires rsync on Spark0 + ring nodes." >&2
	exit 2
fi

echo "== done =="
