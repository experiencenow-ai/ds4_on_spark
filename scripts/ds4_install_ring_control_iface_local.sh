#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]
then
	exec sudo env DS4_NODE_ID="${DS4_NODE_ID:-}" "$0" "$@"
fi

node="${DS4_NODE_ID:-}"
if [ "$node" = "" ] && printf '%s' "${SUDO_USER:-}" | grep -Eq '^spark[0-7]$'
then
	node="$SUDO_USER"
fi
if [ "$node" = "" ] && printf '%s' "${USER:-}" | grep -Eq '^spark[0-7]$'
then
	node="$USER"
fi
if [ "$node" = "" ]
then
	node="$(hostname -s)"
fi
rank="${node#spark}"
if ! printf '%s' "$rank" | grep -Eq '^[0-7]$'
then
	echo "cannot infer spark rank from hostname: $node" >&2
	echo "set DS4_NODE_ID=sparkN and rerun" >&2
	exit 2
fi

ip="10.10.100.$((10 + rank))"
install -d -m 0755 /usr/local/sbin
tmp_script="$(mktemp)"
tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_script" "$tmp_unit"' EXIT

cat >"$tmp_script" <<EOF
#!/bin/sh
set -eu
ip link add ds4ring0 type dummy 2>/dev/null || true
ip addr replace $ip/32 dev ds4ring0
ip link set ds4ring0 up
EOF

cat >"$tmp_unit" <<'EOF'
[Unit]
Description=DS4 200G ring control bind interface
DefaultDependencies=no
After=network-pre.target
Before=network-online.target ds4-ring-200g.service
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ds4-ring-control-iface-apply
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

install -m 0755 "$tmp_script" /usr/local/sbin/ds4-ring-control-iface-apply
install -m 0644 "$tmp_unit" /etc/systemd/system/ds4-ring-control-iface.service
systemctl daemon-reload
systemctl enable --now ds4-ring-control-iface.service
systemctl restart ds4-ring-200g.service
ip -o -4 addr show dev ds4ring0
