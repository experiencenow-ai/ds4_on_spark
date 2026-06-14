#!/usr/bin/env bash
set -euo pipefail

if [ "$(id -u)" -ne 0 ]
then
	exec sudo env DS4_NODE_ID="${DS4_NODE_ID:-}" "$0" "$@"
fi

node="${DS4_NODE_ID:-}"
if [ "$node" = "" ] && printf '%s' "${SUDO_USER:-}" | grep -Eq '^spark([0-9]|[abc])$'
then
	node="$SUDO_USER"
fi
if [ "$node" = "" ] && printf '%s' "${USER:-}" | grep -Eq '^spark([0-9]|[abc])$'
then
	node="$USER"
fi
if [ "$node" = "" ]
then
	node="$(hostname -s)"
fi
case "$node" in
spark[0-9])
	rank="${node#spark}"
	;;
sparka)
	rank=10
	;;
sparkb)
	rank=11
	;;
sparkc)
	rank=12
	;;
*)
	echo "cannot infer spark rank from hostname: $node" >&2
	echo "set DS4_NODE_ID=sparkN and rerun" >&2
	exit 2
	;;
esac

ip="10.10.100.$((10 + rank))"
install -d -m 0755 /usr/local/sbin
tmp_script="$(mktemp)"
tmp_unit="$(mktemp)"
tmp_override="$(mktemp)"
trap 'rm -f "$tmp_script" "$tmp_unit" "$tmp_override"' EXIT

cat >"$tmp_script" <<EOF
#!/bin/sh
set -eu
dev="\${DS4_RING_CONTROL_DEV:-ds4ring0}"
modprobe dummy 2>/dev/null || true
ip link add "\$dev" type dummy 2>/dev/null || true
ip link set "\$dev" up
ip -4 addr replace $ip/32 dev lo
ip -4 addr flush dev "\$dev" scope global 2>/dev/null || true
ip -4 addr replace $ip/32 dev "\$dev"
sysctl -w "net.ipv4.conf.\$dev.rp_filter=0" >/dev/null 2>&1 || true
echo "control-iface-ok \$dev $ip/32"
EOF

cat >"$tmp_unit" <<'EOF'
[Unit]
Description=DS4 ring control dummy interface
After=network-online.target ds4-ring-200g.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ds4-ring-control-iface
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

cat >"$tmp_override" <<'EOF'
[Service]
ExecStart=
ExecStart=/bin/sh -c '/usr/local/sbin/ds4-ring-200g-apply && /usr/local/sbin/ds4-ring-200g-extend13 && /usr/local/sbin/ds4-ring-control-iface'
EOF

install -m 0755 "$tmp_script" /usr/local/sbin/ds4-ring-control-iface
install -m 0644 "$tmp_unit" /etc/systemd/system/ds4-ring-control-iface.service
install -d -m 0755 /etc/systemd/system/ds4-ring-200g.service.d
install -m 0644 "$tmp_override" /etc/systemd/system/ds4-ring-200g.service.d/control-iface.conf
systemctl daemon-reload
systemctl enable ds4-ring-control-iface.service
systemctl restart ds4-ring-control-iface.service
if [ "${DS4_RESTART_RING_SERVICE:-1}" != "0" ]
then
	systemctl restart ds4-ring-200g.service
	systemctl restart ds4-ring-control-iface.service
fi
ip -o -4 addr show dev ds4ring0
