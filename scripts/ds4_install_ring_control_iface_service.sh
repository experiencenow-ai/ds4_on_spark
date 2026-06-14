#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: scripts/ds4_install_ring_control_iface_service.sh [sparkN ...]

Installs and starts ds4-ring-control-iface.service on Spark nodes. The service
recreates the ds4ring0 dummy interface and assigns the node's 10.10.100.N/32
address on every boot and after ds4-ring-200g.service route setup.

The remote install uses sudo and may prompt interactively.
EOF
	exit "${1:-2}"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]
then
	usage 0
fi

nodes=("$@")
if [ "${#nodes[@]}" -eq 0 ]
then
	nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7 spark8 spark9 sparka sparkb sparkc)
fi

remote_repo="${DS4_REMOTE_REPO:-\$HOME/src/ds4_on_spark}"
connect_timeout="${DS4_CONNECT_TIMEOUT:-8}"
ssh_opts="${DS4_SSH_OPTS:-}"

for node in "${nodes[@]}"
do
	echo "==> $node: install ds4-ring-control-iface.service"
	ssh $ssh_opts -tt -o ConnectTimeout="$connect_timeout" "$node" \
		"cd $remote_repo && sudo env DS4_NODE_ID=$node ./scripts/ds4_install_ring_control_iface_local.sh"
done
