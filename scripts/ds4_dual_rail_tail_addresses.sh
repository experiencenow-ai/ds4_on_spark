#!/usr/bin/env bash
set -euo pipefail

APPLY="${APPLY:-0}"
SSH_OPTS=(-n -o BatchMode=yes -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-8}")
ADDRS=(
	"spark7 enp1s0f1np1 10.10.15.1/30"
	"spark8 enp1s0f0np0 10.10.15.2/30"
	"spark8 enp1s0f1np1 10.10.17.1/30"
	"spark9 enp1s0f0np0 10.10.17.2/30"
	"spark9 enp1s0f1np1 10.10.19.1/30"
	"sparka enp1s0f0np0 10.10.19.2/30"
	"sparka enp1s0f1np1 10.10.21.1/30"
	"sparkb enp1s0f0np0 10.10.21.2/30"
	"sparkb enp1s0f1np1 10.10.23.1/30"
	"sparkc enp1s0f0np0 10.10.23.2/30"
	"sparkc enp1s0f1np1 10.10.25.1/30"
	"spark0 enp1s0f0np0 10.10.25.2/30"
)

for row in "${ADDRS[@]}"; do
	set -- $row
	node="$1"
	dev="$2"
	cidr="$3"
	if [ "$APPLY" = "1" ]; then
		echo "== $node $dev $cidr =="
		ssh "${SSH_OPTS[@]}" "$node" "sudo ip addr replace '$cidr' dev '$dev'; ip -br -4 addr show dev '$dev'"
	else
		printf "ssh %s 'sudo ip addr replace %s dev %s'\n" "$node" "$cidr" "$dev"
	fi
done
