#!/usr/bin/env bash
set -euo pipefail

nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
loops=(10.10.100.10 10.10.100.11 10.10.100.12 10.10.100.13 10.10.100.14 10.10.100.15 10.10.100.16 10.10.100.17)
ssh_opts="${DS4_SSH_OPTS:-}"
route_filter="${DS4_ROUTE_FILTER:-}"

for i in 0 1 2 3 4 5 6 7
do
	node="${nodes[$i]}"
	if [ "$route_filter" != "" ] && [ "$route_filter" != "$node" ]
	then
		continue
	fi
	echo "==> $node: configure ds4ring0 ${loops[$i]}/32"
	ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout=4 "$node" "sudo -n ip link add ds4ring0 type dummy 2>/dev/null || true; sudo -n ip addr del ${loops[$i]}/32 dev lo 2>/dev/null || true; sudo -n ip addr replace ${loops[$i]}/32 dev ds4ring0; sudo -n ip link set ds4ring0 up; ip -o -4 addr show dev ds4ring0"
done
