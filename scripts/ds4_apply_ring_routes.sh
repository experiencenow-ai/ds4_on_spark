#!/usr/bin/env bash
set -euo pipefail

nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
loops=(10.10.100.10 10.10.100.11 10.10.100.12 10.10.100.13 10.10.100.14 10.10.100.15 10.10.100.16 10.10.100.17)
p2_f0=(10.10.16.2 10.10.2.2 10.10.4.2 10.10.6.2 10.10.8.2 10.10.10.2 10.10.12.2 10.10.14.2)
p2_f1=(10.10.2.1 10.10.4.1 10.10.6.1 10.10.8.1 10.10.10.1 10.10.12.1 10.10.14.1 10.10.16.1)
prev_gw=(10.10.16.1 10.10.2.1 10.10.4.1 10.10.6.1 10.10.8.1 10.10.10.1 10.10.12.1 10.10.14.1)
next_gw=(10.10.2.2 10.10.4.2 10.10.6.2 10.10.8.2 10.10.10.2 10.10.12.2 10.10.14.2 10.10.16.2)
prev_dev=(enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0)
next_dev=(enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1)
ssh_opts="${DS4_SSH_OPTS:-}"
route_filter="${DS4_ROUTE_FILTER:-}"
topology="${DS4_FABRIC_TOPOLOGY:-line}"

route_direction()
{
	i="$1"
	j="$2"
	if [ "$topology" = "line" ]
	then
		if [ "$j" -gt "$i" ]
		then
			printf 'next\n'
		else
			printf 'prev\n'
		fi
		return
	fi
	cw=$(((j - i + 8) % 8))
	ccw=$(((i - j + 8) % 8))
	if [ "$cw" -le "$ccw" ]
	then
		printf 'next\n'
	else
		printf 'prev\n'
	fi
}

route_replace()
{
	i="$1"
	dst="$2"
	dir="$3"
	if [ "$dir" = "next" ]
	then
		printf 'sudo -n ip route replace %s via %s dev %s src %s\n' "$dst" "${next_gw[$i]}" "${next_dev[$i]}" "${loops[$i]}"
	else
		printf 'sudo -n ip route replace %s via %s dev %s src %s\n' "$dst" "${prev_gw[$i]}" "${prev_dev[$i]}" "${loops[$i]}"
	fi
}

endpoint_exists()
{
	node_index="$1"
	addr="$2"
	if [ "$topology" != "line" ]
	then
		return 0
	fi
	if [ "$node_index" -eq 0 ] && [ "$addr" = "${p2_f0[0]}" ]
	then
		return 1
	fi
	if [ "$node_index" -eq 7 ] && [ "$addr" = "${p2_f1[7]}" ]
	then
		return 1
	fi
	return 0
}

route_cmds()
{
	i="$1"
	addr=""
	dir=""
	printf 'sudo -n sysctl -w net.ipv4.ip_forward=1 >/dev/null\n'
	for j in 0 1 2 3 4 5 6 7
	do
		if [ "$i" -eq "$j" ]
		then
			continue
		fi
		dir="$(route_direction "$i" "$j")"
		route_replace "$i" "${loops[$j]}" "$dir"
		for addr in "${p2_f0[$j]}" "${p2_f1[$j]}"
		do
			if ! endpoint_exists "$j" "$addr"
			then
				continue
			fi
			if [ "$addr" = "${prev_gw[$i]}" ] || [ "$addr" = "${next_gw[$i]}" ]
			then
				continue
			fi
			route_replace "$i" "$addr" "$dir"
		done
	done
	printf 'sudo -n ip route flush cache >/dev/null 2>&1 || true\n'
}

if [ "$topology" != "line" ] && [ "$topology" != "ring" ]
then
	echo "DS4_FABRIC_TOPOLOGY must be line or ring, got '$topology'" >&2
	exit 2
fi

for i in 0 1 2 3 4 5 6 7
do
	node="${nodes[$i]}"
	if [ "$route_filter" != "" ] && [ "$route_filter" != "$node" ]
	then
		continue
	fi
	echo "==> $node: apply generated loopback $topology routes"
	route_cmds "$i" | ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout=4 "$node" sh -e
done
