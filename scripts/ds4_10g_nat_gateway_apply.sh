#!/usr/bin/env bash
set -euo pipefail

WAN_IF="${DS4_NAT_IF:-enP7s7}"
LAN_CIDR="${DS4_NAT_LAN_CIDR:-10.20.0.0/24}"
GATEWAY_ADDR="${DS4_NAT_GATEWAY_ADDR:-10.20.0.13/24}"

ip link set "${WAN_IF}" up
ip addr replace "${GATEWAY_ADDR}" dev "${WAN_IF}"
sysctl -w net.ipv4.ip_forward=1 >/dev/null
sysctl -w net.ipv4.conf.all.rp_filter=0 >/dev/null
sysctl -w net.ipv4.conf.default.rp_filter=0 >/dev/null
sysctl -w "net.ipv4.conf.${WAN_IF}.rp_filter=0" >/dev/null

if ! iptables -w -t nat -C POSTROUTING -s "${LAN_CIDR}" -o "${WAN_IF}" -j MASQUERADE 2>/dev/null
then
	iptables -w -t nat -A POSTROUTING -s "${LAN_CIDR}" -o "${WAN_IF}" -j MASQUERADE
fi

if ! iptables -w -C FORWARD -i "${WAN_IF}" -o "${WAN_IF}" -d "${LAN_CIDR}" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null
then
	iptables -w -I FORWARD 1 -i "${WAN_IF}" -o "${WAN_IF}" -d "${LAN_CIDR}" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
fi

if ! iptables -w -C FORWARD -i "${WAN_IF}" -o "${WAN_IF}" -s "${LAN_CIDR}" -j ACCEPT 2>/dev/null
then
	iptables -w -I FORWARD 1 -i "${WAN_IF}" -o "${WAN_IF}" -s "${LAN_CIDR}" -j ACCEPT
fi

printf 'ds4 10G NAT gateway active on %s for %s via %s\n' "${WAN_IF}" "${LAN_CIDR}" "${GATEWAY_ADDR}"
