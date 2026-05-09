#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark01_mesh_check.sh -- Mac-side Spark0/Spark1 mesh checks (safe)

Usage:
  ops_spark01_mesh_check.sh <spark0_user@host> <spark1_user@host>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Runs a small set of commands on each host and checks basic peer reachability.
  - For stable host key handling, set SSH_OPTS to use a dedicated known-hosts file.
EOF
}

if [ "$#" -ne 2 ]; then
	usage >&2
	exit 2
fi

spark0="$1"
spark1="$2"

host_from_target()
{
	case "$1" in
		*@*)
			echo "${1#*@}"
			return 0
			;;
	esac
	echo "$1"
	return 0
}

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
fi

spark0_host="$(host_from_target "$spark0")"
spark1_host="$(host_from_target "$spark1")"

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

spark_host_checks()
{
	target="$1"
	peer_host="$2"
	role="$3"

	echo "== $role ($target) =="
	ssh_run "$target" "set -eu; date -Is 2>/dev/null || date || true; hostname || true; uname -a || true; id || true; echo \"ulimit_n=$(sh -c 'ulimit -n' 2>/dev/null || true)\"; command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null || true; ip addr 2>/dev/null || true; ip route 2>/dev/null || true"
	echo

	echo "== $role -> peer ping ($peer_host) =="
	ssh_run "$target" "ping -c 2 \"$peer_host\" 2>/dev/null && echo ping_ok || echo ping_failed" || true
	echo
}

echo "== spark01 mesh check (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "spark0: $spark0"
echo "spark1: $spark1"
echo

spark_host_checks "$spark0" "$spark1_host" "spark0"
spark_host_checks "$spark1" "$spark0_host" "spark1"

echo "== done =="
