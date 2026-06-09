#!/usr/bin/env bash
set -euo pipefail

WAN_IF="${WAN_IF:-en0}"
WAN_IP="${WAN_IP:-}"
WAN_GW="${WAN_GW:-}"
LAN_CIDR="${LAN_CIDR:-10.20.0.0/24}"
LAN_GW="${LAN_GW:-10.20.0.1}"
FALLBACK_GW="${FALLBACK_GW:-10.20.0.13}"
LAN_DEV="${LAN_DEV:-enP7s7}"
ANCHOR="${ANCHOR:-com.apple/ds4-fiber-gateway}"
NODES=(
	"spark0 10.20.0.10"
	"spark1 10.20.0.11"
	"spark2 10.20.0.12"
	"spark3 10.20.0.13"
	"spark4 10.20.0.14"
	"spark5 10.20.0.15"
	"spark6 10.20.0.16"
	"spark7 10.20.0.17"
	"spark8 10.20.0.18"
	"spark9 10.20.0.19"
	"sparka 10.20.0.20"
	"sparkb 10.20.0.21"
	"sparkc 10.20.0.22"
)

if [ -z "$WAN_IP" ] && command -v ifconfig >/dev/null 2>&1; then
	WAN_IP="$(ifconfig "$WAN_IF" | awk '/inet / {print $2}' | grep -Ev '^(10\.20\.0\.1|169\.254\.|127\.)' | head -1 || true)"
fi
if [ -z "$WAN_GW" ] && command -v ipconfig >/dev/null 2>&1; then
	WAN_GW="$(ipconfig getpacket "$WAN_IF" | awk -F'[{}]' '/router \(ip_mult\)/ {print $2; exit}' || true)"
fi

cat <<EOF
# Review before applying. This script only prints the known-good shape.
# Mac side:
sudo route -n add -net 0.0.0.0/1 ${WAN_GW:-FIBER_GATEWAY}
sudo route -n add -net 128.0.0.0/1 ${WAN_GW:-FIBER_GATEWAY}
sudo sysctl -w net.inet.ip.forwarding=1

# PF anchor load:
sudo pfctl -E
sudo pfctl -a $ANCHOR -f /private/tmp/ds4_fiber_gateway_hosts.pf

# /private/tmp/ds4_fiber_gateway_hosts.pf:
EOF

for pair in "${NODES[@]}"; do
	set -- $pair
	ip="$2"
	echo "nat on $WAN_IF inet from $ip to ! $LAN_CIDR -> ${WAN_IP:-FIBER_IP}"
done
for pair in "${NODES[@]}"; do
	set -- $pair
	ip="$2"
	echo "pass in quick on $WAN_IF inet from $ip to ! $LAN_CIDR keep state"
done
echo "pass out quick on $WAN_IF inet from ${WAN_IP:-FIBER_IP} to any keep state"

cat <<EOF

# Spark side preferred route:
# spark3 is the fallback gateway exception and must not add a self fallback via $FALLBACK_GW.
EOF

for pair in "${NODES[@]}"; do
	set -- $pair
	node="$1"
	if [ "$node" = "spark3" ]; then
		echo "ssh $node 'sudo ip route replace default via $LAN_GW dev $LAN_DEV metric 50'"
	else
		echo "ssh $node 'sudo ip route replace default via $LAN_GW dev $LAN_DEV metric 50; sudo ip route replace default via $FALLBACK_GW dev $LAN_DEV metric 100'"
	fi
done

