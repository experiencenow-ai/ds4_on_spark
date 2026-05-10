#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark01_mesh_check.sh -- Mac-side Spark0/Spark1 mesh checks (safe)

Usage:
  ops_spark01_mesh_check.sh [--tcp <port>]... <spark0_user@host> <spark1_user@host>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Runs a small set of commands on each host and checks basic peer reachability.
  - `--tcp <port>` runs a best-effort `nc -z` probe to the peer (only meaningful if something is listening).
  - For stable host key handling, set SSH_OPTS to use a dedicated known-hosts file.
EOF
}

tcp_ports=""

while [ $# -gt 0 ]; do
	case "$1" in
		--tcp)
			tcp_ports="$tcp_ports ${2:-}"
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

	echo "== $role -> peer route get ($peer_host) (best effort) =="
	ssh_run "$target" "ip -4 route get \"$peer_host\" 2>/dev/null | sed -n '1p' || true" || true
	echo

	if [ "$tcp_ports" != "" ]; then
		echo "== $role -> peer tcp probes ($peer_host) (optional) =="
		ssh_run "$target" sh -c '
set -eu
peer="${1:-}"
shift || true
if command -v nc >/dev/null 2>&1; then
	for p in "$@"; do
		if nc -z -w 2 "$peer" "$p" 2>/dev/null; then
			echo "tcp_ok ${peer}:${p}"
		else
			echo "tcp_failed ${peer}:${p}"
		fi
	done
else
	echo "nc_missing; skip"
fi
' sh "$peer_host" $tcp_ports || true
		echo
	fi
}

echo "== spark01 mesh check (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "spark0: $spark0"
echo "spark1: $spark1"
echo

spark_host_checks "$spark0" "$spark1_host" "spark0"
spark_host_checks "$spark1" "$spark0_host" "spark1"

echo "== done =="
