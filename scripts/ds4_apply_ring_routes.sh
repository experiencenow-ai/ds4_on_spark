#!/usr/bin/env bash
set -euo pipefail

nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
loops=(10.10.100.10 10.10.100.11 10.10.100.12 10.10.100.13 10.10.100.14 10.10.100.15 10.10.100.16 10.10.100.17)
prev_gw=(10.10.16.1 10.10.2.1 10.10.4.1 10.10.6.1 10.10.8.1 10.10.10.1 10.10.12.1 10.10.14.1)
next_gw=(10.10.2.2 10.10.4.2 10.10.6.2 10.10.8.2 10.10.10.2 10.10.12.2 10.10.14.2 10.10.16.2)
prev_dev=(enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0)
next_dev=(enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1)
ssh_opts="${DS4_SSH_OPTS:-}"
route_filter="${DS4_ROUTE_FILTER:-}"

route_cmds()
{
	i="$1"
	printf 'sudo -n sysctl -w net.ipv4.ip_forward=1 >/dev/null\n'
	for j in 0 1 2 3 4 5 6 7
	do
		if [ "$i" -eq "$j" ]
		then
			continue
		fi
		cw=$(((j - i + 8) % 8))
		ccw=$(((i - j + 8) % 8))
		if [ "$cw" -le "$ccw" ]
		then
			printf 'sudo -n ip route replace %s via %s dev %s src %s\n' "${loops[$j]}" "${next_gw[$i]}" "${next_dev[$i]}" "${loops[$i]}"
		else
			printf 'sudo -n ip route replace %s via %s dev %s src %s\n' "${loops[$j]}" "${prev_gw[$i]}" "${prev_dev[$i]}" "${loops[$i]}"
		fi
	done
	printf 'sudo -n ip route flush cache >/dev/null 2>&1 || true\n'
}

for i in 0 1 2 3 4 5 6 7
do
	node="${nodes[$i]}"
	if [ "$route_filter" != "" ] && [ "$route_filter" != "$node" ]
	then
		continue
	fi
	echo "==> $node: apply generated loopback ring routes"
	route_cmds "$i" | ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout=4 "$node" sh
done
