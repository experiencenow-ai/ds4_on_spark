#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: scripts/ds4_install_mac_fast_internet_gateway_service.sh [sparkN ...]

Installs and starts the DS4 Mac fast internet gateway route refresher on Spark
nodes. When no nodes are provided, the node list comes from
v2/profiles/transfer/spark_200g.json.

The remote install uses sudo and may prompt interactively.

Environment:
  DS4_SPARK_FLEET_TOPOLOGY=v2/profiles/transfer/spark_200g.json
  DS4_CONNECT_TIMEOUT=8
  DS4_SSH_OPTS=...
  DS4_SCP_OPTS=...
  LAN_GW=10.20.0.1
  FALLBACK_GW=10.20.0.13
  FALLBACK_GATEWAY_NODE=spark3
  LAN_DEV=enP7s7
  DNS_SERVERS="1.1.1.1 8.8.8.8"
EOF
	exit "${1:-2}"
}

quote()
{
	printf "'"
	printf "%s" "$1" | sed "s/'/'\\\\''/g"
	printf "'"
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]
then
	usage 0
fi

repo_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
topology_path="${DS4_SPARK_FLEET_TOPOLOGY:-$repo_dir/v2/profiles/transfer/spark_200g.json}"
connect_timeout="${DS4_CONNECT_TIMEOUT:-8}"
ssh_opts="${DS4_SSH_OPTS:-}"
scp_opts="${DS4_SCP_OPTS:-}"
LAN_GW="${LAN_GW:-10.20.0.1}"
FALLBACK_GW="${FALLBACK_GW:-10.20.0.13}"
FALLBACK_GATEWAY_NODE="${FALLBACK_GATEWAY_NODE:-spark3}"
LAN_DEV="${LAN_DEV:-enP7s7}"
DNS_SERVERS="${DNS_SERVERS:-1.1.1.1 8.8.8.8}"

nodes=("$@")

load_default_nodes()
{
	python3 - "$topology_path" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    topology = json.load(handle)
for node in topology.get("nodes", []):
    node_id = node.get("node_id")
    if node_id:
        print(node_id)
PY
}

node_ssh_target()
{
	local node_id="$1"
	python3 - "$topology_path" "$node_id" <<'PY'
import json
import sys

path = sys.argv[1]
node_id = sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as handle:
        topology = json.load(handle)
except (OSError, ValueError, json.JSONDecodeError):
    print(node_id)
    raise SystemExit(0)
for node in topology.get("nodes", []):
    if node.get("node_id") == node_id:
        print(node.get("host") or node_id)
        raise SystemExit(0)
print(node_id)
PY
}

if [ "${#nodes[@]}" -eq 0 ]
then
	while IFS= read -r node
	do
		if [ "$node" != "" ]
		then
			nodes+=("$node")
		fi
	done < <(load_default_nodes)
	if [ "${#nodes[@]}" -eq 0 ]
	then
		echo "no default Spark nodes found in topology: $topology_path" >&2
		exit 15
	fi
fi

for node in "${nodes[@]}"
do
	host="$(node_ssh_target "$node")"
	target="$node@$host"
	tmp_dir="/tmp/ds4-mac-fast-internet-gateway-install"
	echo "==> $node: install ds4-mac-fast-internet-gateway service"
	ssh $ssh_opts -o ConnectTimeout="$connect_timeout" "$target" "rm -rf $(quote "$tmp_dir") && mkdir -p $(quote "$tmp_dir")"
	scp $scp_opts -o ConnectTimeout="$connect_timeout" \
		"$repo_dir/scripts/ds4_mac_fast_internet_gateway_local.sh" \
		"$repo_dir/deploy/systemd/ds4-mac-fast-internet-gateway.service" \
		"$repo_dir/deploy/systemd/ds4-mac-fast-internet-gateway.timer" \
		"$target:$tmp_dir/" >/dev/null
	remote="set -e"
	remote="$remote; install -m 0755 $(quote "$tmp_dir/ds4_mac_fast_internet_gateway_local.sh") /usr/local/sbin/ds4-mac-fast-internet-gateway"
	remote="$remote; install -m 0644 $(quote "$tmp_dir/ds4-mac-fast-internet-gateway.service") /etc/systemd/system/ds4-mac-fast-internet-gateway.service"
	remote="$remote; install -m 0644 $(quote "$tmp_dir/ds4-mac-fast-internet-gateway.timer") /etc/systemd/system/ds4-mac-fast-internet-gateway.timer"
	remote="$remote; printf '%s\n' $(quote "DS4_NODE_ID=$node") $(quote "LAN_GW=$LAN_GW") $(quote "FALLBACK_GW=$FALLBACK_GW") $(quote "FALLBACK_GATEWAY_NODE=$FALLBACK_GATEWAY_NODE") $(quote "LAN_DEV=$LAN_DEV") $(quote "DNS_SERVERS=\"$DNS_SERVERS\"") > /etc/ds4-mac-fast-internet-gateway.env"
	remote="$remote; systemctl daemon-reload"
	remote="$remote; systemctl enable --now ds4-mac-fast-internet-gateway.timer"
	remote="$remote; systemctl start ds4-mac-fast-internet-gateway.service"
	remote="$remote; rm -rf $(quote "$tmp_dir")"
	ssh $ssh_opts -tt -o ConnectTimeout="$connect_timeout" "$target" "sudo sh -lc $(quote "$remote")"
done
