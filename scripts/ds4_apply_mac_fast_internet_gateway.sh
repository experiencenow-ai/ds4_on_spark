#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: scripts/ds4_apply_mac_fast_internet_gateway.sh [--execute] [--no-dns] [spark0 ...]

Restores the canonical Spark internet route through the Mac 10.20 gateway.
Dry-run is the default; pass --execute to run the sudo remote route updates.

Environment:
  LAN_GW=10.20.0.1                 preferred Mac gateway
  FALLBACK_GW=10.20.0.13           fallback gateway for non-spark3 nodes
  LAN_DEV=enP7s7                   Spark management NIC
  DNS_SERVERS="1.1.1.1 8.8.8.8"    resolvectl DNS servers for LAN_DEV
  SSH_CONNECT_TIMEOUT=8
  DS4_SSH_OPTS=...                 extra ssh options
EOF
	exit "${1:-2}"
}

quote()
{
	printf "%q" "$1"
}

node_ip()
{
	case "$1" in
	spark0) echo 10.20.0.10 ;;
	spark1) echo 10.20.0.11 ;;
	spark2) echo 10.20.0.12 ;;
	spark3) echo 10.20.0.13 ;;
	spark4) echo 10.20.0.14 ;;
	spark5) echo 10.20.0.15 ;;
	spark6) echo 10.20.0.16 ;;
	spark7) echo 10.20.0.17 ;;
	spark8) echo 10.20.0.18 ;;
	spark9) echo 10.20.0.19 ;;
	sparka) echo 10.20.0.20 ;;
	sparkb) echo 10.20.0.21 ;;
	sparkc) echo 10.20.0.22 ;;
	*) return 1 ;;
	esac
}

execute=0
configure_dns=1
nodes=()
while [ "$#" -gt 0 ]
do
	case "$1" in
	-h|--help)
		usage 0
		;;
	--execute)
		execute=1
		;;
	--no-dns)
		configure_dns=0
		;;
	--)
		shift
		nodes+=("$@")
		break
		;;
	-*)
		echo "unknown option: $1" >&2
		usage
		;;
	*)
		nodes+=("$1")
		;;
	esac
	shift
done

if [ "${#nodes[@]}" -eq 0 ]; then
	nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7 spark8 spark9 sparka sparkb sparkc)
fi

LAN_GW="${LAN_GW:-10.20.0.1}"
FALLBACK_GW="${FALLBACK_GW:-10.20.0.13}"
LAN_DEV="${LAN_DEV:-enP7s7}"
DNS_SERVERS="${DNS_SERVERS:-1.1.1.1 8.8.8.8}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-8}"
ssh_opts="${DS4_SSH_OPTS:-}"

for node in "${nodes[@]}"
do
	ip="$(node_ip "$node")" || {
		echo "unknown Spark node: $node" >&2
		exit 3
	}
	remote="set -e; ip route replace default via $(quote "$LAN_GW") dev $(quote "$LAN_DEV") metric 50"
	if [ "$node" != "spark3" ]; then
		remote="$remote; ip route replace default via $(quote "$FALLBACK_GW") dev $(quote "$LAN_DEV") metric 100"
	fi
	if [ "$configure_dns" = "1" ]; then
		remote="$remote; if command -v resolvectl >/dev/null 2>&1; then resolvectl dns $(quote "$LAN_DEV") $DNS_SERVERS; resolvectl domain $(quote "$LAN_DEV") '~.'; fi"
	fi
	remote="$remote; ip -4 route get 1.1.1.1 | head -1; getent hosts github.com | head -1 || true"
	if [ "$execute" != "1" ]; then
		printf "ssh -tt %s@%s %s\n" "$node" "$ip" "$(quote "sudo sh -lc $(quote "$remote")")"
		continue
	fi
	echo "==> $node@$ip: apply Mac fast internet gateway"
	ssh $ssh_opts -tt -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" "$node@$ip" "sudo sh -lc $(quote "$remote")"
done
