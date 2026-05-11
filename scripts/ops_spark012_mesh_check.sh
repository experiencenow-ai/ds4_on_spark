#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark012_mesh_check.sh -- Mac-side Spark0/Spark1/Spark2 mesh checks (safe)

Usage:
  ops_spark012_mesh_check.sh [--topology ring|full] [--tcp <port>]... <spark0_user@host> <spark1_user@host> <spark2_user@host>

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Runs a small set of commands on each host and checks basic peer reachability.
  - With `--topology ring` (default), each host checks ping/route to its ring neighbors.
    With `--topology full`, each host checks all other hosts.
  - With 3 nodes, ring and full are effectively equivalent (two peers either way).
  - `--tcp <port>` runs a best-effort `nc -z` probe to peers (only meaningful if something is listening).
  - For stable host key handling, set SSH_OPTS to use a dedicated known-hosts file.
EOF
}

topology="ring"
tcp_ports=""

while [ $# -gt 0 ]; do
	case "$1" in
		--topology)
			topology="${2:-}"
			shift 2
			;;
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

case "$topology" in
	ring|full)
		;;
	*)
		echo "invalid --topology: $topology (expected ring|full)" >&2
		exit 2
		;;
esac

if [ "$#" -ne 3 ]; then
	usage >&2
	exit 2
fi

spark0="$1"
spark1="$2"
spark2="$3"

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

h0="$(host_from_target "$spark0")"
h1="$(host_from_target "$spark1")"
h2="$(host_from_target "$spark2")"

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

spark_host_checks()
{
	target="$1"
	role="$2"
	peer_hosts="$3"

	echo "== $role ($target) =="
	ssh_run "$target" "set -eu; date -Is 2>/dev/null || date || true; hostname || true; uname -a || true; id || true; echo \"ulimit_n=$(sh -c 'ulimit -n' 2>/dev/null || true)\"; command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null || true; ip addr 2>/dev/null || true; ip route 2>/dev/null || true"
	echo

	for peer in $peer_hosts; do
		echo "== $role -> peer ping ($peer) =="
		ssh_run "$target" "ping -c 2 \"$peer\" 2>/dev/null && echo ping_ok || echo ping_failed" || true
		echo

		echo "== $role -> peer route get ($peer) (best effort) =="
		ssh_run "$target" "ip -4 route get \"$peer\" 2>/dev/null | sed -n '1p' || true" || true
		echo

		if [ "$tcp_ports" != "" ]; then
			echo "== $role -> peer tcp probes ($peer) (optional) =="
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
' sh "$peer" $tcp_ports || true
			echo
		fi
	done
}

peers_for_role()
{
	role="$1"
	case "$topology" in
		ring)
			case "$role" in
				spark0) echo "$h2 $h1"; return 0 ;;
				spark1) echo "$h0 $h2"; return 0 ;;
				spark2) echo "$h1 $h0"; return 0 ;;
			esac
			;;
		full)
			case "$role" in
				spark0) echo "$h1 $h2"; return 0 ;;
				spark1) echo "$h0 $h2"; return 0 ;;
				spark2) echo "$h0 $h1"; return 0 ;;
			esac
			;;
	esac
	return 1
}

echo "== spark012 mesh check (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "topology=$topology"
echo "spark0: $spark0"
echo "spark1: $spark1"
echo "spark2: $spark2"
echo

spark_host_checks "$spark0" "spark0" "$(peers_for_role spark0)"
spark_host_checks "$spark1" "spark1" "$(peers_for_role spark1)"
spark_host_checks "$spark2" "spark2" "$(peers_for_role spark2)"

echo "== done =="

