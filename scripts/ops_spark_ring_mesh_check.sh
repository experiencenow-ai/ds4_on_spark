#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_ring_mesh_check.sh -- Mac-side Spark ring mesh checks (safe)

Usage:
  ops_spark_ring_mesh_check.sh [--topology ring|full] [--tcp <port>]... <spark0_user@host> <spark1_user@host> [spark2_user@host ...]

Environment:
  SSH_OPTS   Optional ssh options override.

Notes:
  - Non-destructive; intended to run from the Mac.
  - Host order defines rank/order: arg0=spark0, arg1=spark1, etc.
  - With `--topology ring` (default), each host checks its previous/next ring neighbors.
  - With `--topology full`, each host checks all other hosts.
  - `--tcp <port>` runs a best-effort `nc -z` probe to peers.
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

if [ "$#" -lt 2 ]; then
	usage >&2
	exit 2
fi

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

node_count="$#"
i=0
while [ "$#" -gt 0 ]; do
	eval "target_$i=\$1"
	host="$(host_from_target "$1")"
	eval "host_$i=\$host"
	i=$((i + 1))
	shift
done

if [ "${SSH_OPTS:-}" = "" ]; then
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
fi

value_at()
{
	prefix="$1"
	idx="$2"
	eval "printf '%s' \"\${${prefix}_${idx}:-}\""
}

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

peers_for_index()
{
	idx="$1"
	peers=""
	case "$topology" in
		ring)
			if [ "$node_count" -eq 2 ]; then
				if [ "$idx" -eq 0 ]; then
					peers="$(value_at host 1)"
				else
					peers="$(value_at host 0)"
				fi
			else
				prev=$(((idx + node_count - 1) % node_count))
				next=$(((idx + 1) % node_count))
				peers="$(value_at host "$prev") $(value_at host "$next")"
			fi
			;;
		full)
			j=0
			while [ "$j" -lt "$node_count" ]; do
				if [ "$j" -ne "$idx" ]; then
					peers="$peers $(value_at host "$j")"
				fi
				j=$((j + 1))
			done
			;;
	esac
	echo "$peers"
}

echo "== spark ring mesh check (Mac-side) =="
date -Is 2>/dev/null || date || true
echo "topology=$topology"
echo "node_count=$node_count"
i=0
while [ "$i" -lt "$node_count" ]; do
	echo "spark$i: $(value_at target "$i")"
	i=$((i + 1))
done
echo

i=0
while [ "$i" -lt "$node_count" ]; do
	spark_host_checks "$(value_at target "$i")" "spark$i" "$(peers_for_index "$i")"
	i=$((i + 1))
done

echo "== done =="
