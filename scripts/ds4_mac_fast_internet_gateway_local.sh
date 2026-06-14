#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: sudo DS4_NODE_ID=sparkN scripts/ds4_mac_fast_internet_gateway_local.sh

Installs the Spark node's canonical management-network internet route through
the Mac gateway. Intended to run as root from systemd after boot and
periodically afterward so route/DNS drift is repaired without manual SSH.

Environment:
  DS4_NODE_ID=sparkN                required when hostname is not sparkN
  LAN_GW=10.20.0.1                 preferred Mac gateway
  FALLBACK_GW=10.20.0.13           fallback gateway for non-spark3 nodes
  FALLBACK_GATEWAY_NODE=spark3      node that owns FALLBACK_GW
  LAN_DEV=enP7s7                   Spark management NIC
  DNS_SERVERS="1.1.1.1 8.8.8.8"    resolvectl DNS servers for LAN_DEV
  DS4_CONFIGURE_DNS=1              set 0 to skip DNS setup
EOF
	exit "${1:-2}"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]
then
	usage 0
fi

if [ "$(id -u)" != "0" ]
then
	echo "ds4-mac-fast-internet-gateway must run as root" >&2
	exit 77
fi

node="${DS4_NODE_ID:-$(hostname -s)}"
case "$node" in
spark0|spark1|spark2|spark3|spark4|spark5|spark6|spark7|spark8|spark9|sparka|sparkb|sparkc)
	;;
*)
	echo "cannot infer Spark node id from hostname: $node" >&2
	echo "set DS4_NODE_ID=sparkN and rerun" >&2
	exit 78
	;;
esac

LAN_GW="${LAN_GW:-10.20.0.1}"
FALLBACK_GW="${FALLBACK_GW:-10.20.0.13}"
FALLBACK_GATEWAY_NODE="${FALLBACK_GATEWAY_NODE:-spark3}"
LAN_DEV="${LAN_DEV:-enP7s7}"
DNS_SERVERS="${DNS_SERVERS:-1.1.1.1 8.8.8.8}"
DS4_CONFIGURE_DNS="${DS4_CONFIGURE_DNS:-1}"

ip link show "$LAN_DEV" >/dev/null
ip route replace default via "$LAN_GW" dev "$LAN_DEV" metric 50
if [ "$node" != "$FALLBACK_GATEWAY_NODE" ] && [ "$FALLBACK_GW" != "" ]
then
	ip route replace default via "$FALLBACK_GW" dev "$LAN_DEV" metric 100
fi
if [ "$DS4_CONFIGURE_DNS" = "1" ] && command -v resolvectl >/dev/null 2>&1
then
	resolvectl dns "$LAN_DEV" $DNS_SERVERS
	resolvectl domain "$LAN_DEV" "~."
fi
ip -4 route get 1.1.1.1 | head -1
getent hosts github.com | head -1 || true
