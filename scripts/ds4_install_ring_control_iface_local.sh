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
tmp_route_apply="$(mktemp)"
tmp_route_extend="$(mktemp)"
tmp_unit="$(mktemp)"
tmp_override="$(mktemp)"
trap 'rm -f "$tmp_script" "$tmp_route_apply" "$tmp_route_extend" "$tmp_unit" "$tmp_override"' EXIT
override_dir="/etc/systemd/system/ds4-ring-200g.service.d"
override_file="$override_dir/zz-ds4-ring-control-iface.conf"

cat >"$tmp_script" <<EOF
#!/bin/sh
set -eu
dev="\${DS4_RING_CONTROL_DEV:-ds4ring0}"
modprobe dummy 2>/dev/null || true
ip link add "\$dev" type dummy 2>/dev/null || true
ip link set "\$dev" up
ip -o -4 addr show dev lo | awk '{print \$4}' | while read addr
do
	case "\$addr" in
	10.10.100.*)
		if [ "\$addr" != "$ip/32" ]
		then
			ip -4 addr del "\$addr" dev lo 2>/dev/null || true
		fi
		;;
	esac
done
ip -4 addr replace $ip/32 dev lo
ip -4 addr flush dev "\$dev" scope global 2>/dev/null || true
ip -4 addr replace $ip/32 dev "\$dev"
sysctl -w "net.ipv4.conf.\$dev.rp_filter=0" >/dev/null 2>&1 || true
echo "control-iface-ok \$dev $ip/32"
EOF

cat >"$tmp_route_apply" <<EOF
#!/bin/sh
set -eu
rank=$rank
src_ip="$ip"

rail_up()
{
	dev="\$1"
	[ -e "/sys/class/net/\$dev/carrier" ] && [ "\$(cat "/sys/class/net/\$dev/carrier" 2>/dev/null || echo 0)" = "1" ]
}

next_hop_ready()
{
	dev="\$1"
	via="\$2"
	rail_up "\$dev" && ping -I "\$dev" -c 1 -W 1 "\$via" >/dev/null 2>&1
}

setup_rail()
{
	dev="\$1"
	cidr="\$2"
	if [ -e "/sys/class/net/\$dev" ]
	then
		ip link set "\$dev" mtu 9000 up 2>/dev/null || true
		ip addr replace "\$cidr" dev "\$dev" 2>/dev/null || true
		sysctl -w "net.ipv4.conf.\$dev.rp_filter=0" >/dev/null 2>&1 || true
	fi
}

install_forward_accept()
{
	if command -v iptables >/dev/null 2>&1
	then
		iptables -C DOCKER-USER -s 10.10.100.0/24 -d 10.10.100.0/24 -j ACCEPT 2>/dev/null || iptables -I DOCKER-USER 1 -s 10.10.100.0/24 -d 10.10.100.0/24 -j ACCEPT 2>/dev/null || true
		iptables -C FORWARD -s 10.10.100.0/24 -d 10.10.100.0/24 -j ACCEPT 2>/dev/null || iptables -I FORWARD 1 -s 10.10.100.0/24 -d 10.10.100.0/24 -j ACCEPT 2>/dev/null || true
	fi
}

if [ "\$rank" -gt 0 ]
then
	setup_rail "enp1s0f0np0" "10.10.\$(((rank * 2) - 1)).2/30"
fi
if [ "\$rank" -lt 12 ]
then
	setup_rail "enp1s0f1np1" "10.10.\$(((rank * 2) + 1)).1/30"
fi
install_forward_accept

target_rank=0
while [ "\$target_rank" -lt 13 ]
do
	if [ "\$target_rank" -ne "\$rank" ]
	then
		target_ip="10.10.100.\$((10 + target_rank))"
		if [ "\$target_rank" -gt "\$rank" ]
		then
			primary_via="10.10.\$(((rank + 1) * 2)).2"
			primary_dev="enP2p1s0f1np1"
			fallback_via="10.10.\$(((rank * 2) + 1)).2"
			fallback_dev="enp1s0f1np1"
		else
			primary_via="10.10.\$((rank * 2)).1"
			primary_dev="enP2p1s0f0np0"
			fallback_via="10.10.\$(((rank * 2) - 1)).1"
			fallback_dev="enp1s0f0np0"
		fi
		if next_hop_ready "\$primary_dev" "\$primary_via"
		then
			via="\$primary_via"
			dev="\$primary_dev"
		elif next_hop_ready "\$fallback_dev" "\$fallback_via"
		then
			via="\$fallback_via"
			dev="\$fallback_dev"
		else
			via="\$primary_via"
			dev="\$primary_dev"
		fi
		ip route replace "\$target_ip" via "\$via" dev "\$dev" src "\$src_ip"
	fi
	target_rank=\$((target_rank + 1))
done
echo "ring-routes-ok spark$rank $ip/32"
EOF

cat >"$tmp_route_extend" <<'EOF'
#!/bin/sh
set -eu
echo "ring-extend13-ok"
EOF

cat >"$tmp_unit" <<'EOF'
[Unit]
Description=DS4 ring control dummy interface
DefaultDependencies=no
After=local-fs.target systemd-modules-load.service
Before=network-pre.target network-online.target ds4-ring-200g.service
Wants=network-pre.target
StartLimitIntervalSec=120
StartLimitBurst=20

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/ds4-ring-control-iface
RemainAfterExit=yes
Restart=on-failure
RestartSec=2s

[Install]
WantedBy=multi-user.target
EOF

cat >"$tmp_override" <<'EOF'
[Service]
ExecStart=
ExecStart=/bin/sh -c '/usr/local/sbin/ds4-ring-control-iface && if [ -x /usr/local/sbin/ds4-ring-200g-apply ] && [ -x /usr/local/sbin/ds4-ring-200g-extend13 ]; then /usr/local/sbin/ds4-ring-200g-apply && /usr/local/sbin/ds4-ring-200g-extend13; else /usr/local/sbin/ds4-ring-200g; fi && /usr/local/sbin/ds4-ring-control-iface'
EOF

install -m 0755 "$tmp_script" /usr/local/sbin/ds4-ring-control-iface
install -m 0755 "$tmp_route_apply" /usr/local/sbin/ds4-ring-200g-apply
install -m 0755 "$tmp_route_extend" /usr/local/sbin/ds4-ring-200g-extend13
install -m 0644 "$tmp_unit" /etc/systemd/system/ds4-ring-control-iface.service
install -d -m 0755 "$override_dir"
rm -f "$override_dir/control-iface.conf"
install -m 0644 "$tmp_override" "$override_file"
systemctl daemon-reload
systemctl reset-failed ds4-ring-control-iface.service ds4-ring-200g.service 2>/dev/null || true
systemctl enable ds4-ring-control-iface.service
systemctl restart ds4-ring-control-iface.service
if [ "${DS4_RESTART_RING_SERVICE:-1}" != "0" ]
then
	systemctl restart ds4-ring-200g.service
	systemctl restart ds4-ring-control-iface.service
fi
ip -o -4 addr show dev ds4ring0
