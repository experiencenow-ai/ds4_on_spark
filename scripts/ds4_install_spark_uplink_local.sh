#!/usr/bin/env bash
set -euo pipefail

usage()
{
	cat >&2 <<'EOF'
usage: sudo scripts/ds4_install_spark_uplink_local.sh <sparkN>

The ASUS PSK must already exist at /etc/ds4-uplink/asus.psk with mode 0600.
Profiles are installed immediately, then activated by a detached systemd job
so replacing enP7s7's connection cannot strand the invoking SSH process.
EOF
	exit "${1:-2}"
}

if [ "$(id -u)" -ne 0 ]
then
	exec sudo "$0" "$@"
fi

node_id="${1:-}"
[ -n "$node_id" ] || usage
script_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
psk_file="/etc/ds4-uplink/asus.psk"
[ -s "$psk_file" ] || { echo "missing ASUS PSK: $psk_file" >&2; exit 3; }
[ "$(stat -c %a "$psk_file")" = "600" ] || { echo "ASUS PSK must have mode 0600: $psk_file" >&2; exit 4; }
install -d -m 0755 /usr/local/sbin /etc/ds4-uplink /var/lib/ds4-uplink
install -m 0755 "$script_dir/ds4_spark_uplink.py" /usr/local/sbin/ds4_spark_uplink.py
install -m 0755 "$script_dir/ds4_spark_uplink_canary.sh" /usr/local/sbin/ds4_spark_uplink_canary.sh
install -m 0644 "$repo_root/deploy/systemd/ds4-uplink-monitor.service" /etc/systemd/system/ds4-uplink-monitor.service
install -m 0644 "$repo_root/deploy/systemd/ds4-uplink-monitor.timer" /etc/systemd/system/ds4-uplink-monitor.timer
/usr/local/sbin/ds4_spark_uplink.py plan --node-id "$node_id" --output /etc/ds4-uplink/config.json
stamp=$(date -u +%Y%m%dT%H%M%SZ)
{
	date -u +%Y-%m-%dT%H:%M:%SZ
	nmcli -t -f NAME,UUID,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY con show
	ip -o -4 addr show
	ip -4 route show
} >"/var/lib/ds4-uplink/preinstall-${node_id}-${stamp}.txt"
systemctl daemon-reload
systemctl disable --now ds4-internet-client.timer ds4-internet-gateway.timer >/dev/null 2>&1 || true
systemctl enable ds4-uplink-monitor.timer >/dev/null
systemd-run --collect --unit="ds4-uplink-apply-${node_id}" --on-active=3s \
	/bin/sh -c '/usr/local/sbin/ds4_spark_uplink.py apply && systemctl start ds4-uplink-monitor.service && systemctl start ds4-uplink-monitor.timer'
echo "uplink-apply-scheduled node=$node_id delay=3s"
