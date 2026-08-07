#!/usr/bin/env bash
set -euo pipefail

controller="/usr/local/sbin/ds4_spark_uplink.py"
timer="ds4-uplink-monitor.timer"
wired_rule_priority="10420"
asus_rule_priority="10421"
asus_retry_file="/run/ds4-uplink/asus_retry_after"
timer_was_active="no"

fail()
{
	echo "uplink_canary_failed reason=$1" >&2
	exit 1
}

remove_rule()
{
	local priority="$1"
	while ip rule del priority "$priority" 2>/dev/null
	do
		:
	done
}

restore()
{
	local attempt
	local restored="no"
	remove_rule "$asus_rule_priority"
	remove_rule "$wired_rule_priority"
	rm -f "$asus_retry_file"
	for attempt in $(seq 1 12)
	do
		if "$controller" monitor
		then
			restored="yes"
			break
		fi
		sleep 2
	done
	if [ "$timer_was_active" = "yes" ]
	then
		if ! systemctl start "$timer"
		then
			restored="no"
		fi
	fi
	[ "$restored" = "yes" ] && return 0
	echo "uplink_canary_restore_failed attempts=12" >&2
	return 1
}

on_exit()
{
	local status="$?"
	trap - EXIT INT TERM
	if ! restore
	then
		status=1
	fi
	exit "$status"
}

expect_path()
{
	local expected="$1"
	local actual
	actual=$(cat /run/ds4-uplink/path 2>/dev/null || true)
	[ "$actual" = "$expected" ] || fail "expected_${expected}_got_${actual:-missing}"
	echo "uplink_canary_path path=$actual"
}

if [ "$(id -u)" -ne 0 ]
then
	exec sudo "$0" "$@"
fi
[ -x "$controller" ] || fail "controller_missing"
if systemctl is-active --quiet "$timer"
then
	timer_was_active="yes"
	systemctl stop "$timer"
fi
trap on_exit EXIT INT TERM
ip rule show | grep -Eq "^(${wired_rule_priority}|${asus_rule_priority}):" && fail "test_rule_priority_in_use"
audit=$("$controller" audit)
wired_cidr=$(printf '%s\n' "$audit" | awk -F= '$1 == "expected_asus_wired" {print $2}')
wired_address="${wired_cidr%/*}"
[ -n "$wired_address" ] || fail "wired_address_missing"
"$controller" monitor
expect_path "wired"
active_wifi=$(nmcli -g GENERAL.CONNECTION device show wlP9s9)
[ "$active_wifi" = "ds4-uplink-asus" ] || fail "baseline_wifi_${active_wifi:-missing}"
ip rule add priority "$wired_rule_priority" from "$wired_address/32" blackhole
"$controller" monitor
expect_path "asus_wifi"
asus_address=$(ip -o -4 addr show dev wlP9s9 scope global | awk '$4 ~ /^192[.]168[.]50[.]/ {split($4,address,"/"); print address[1]; exit}')
[ -n "$asus_address" ] || fail "asus_wifi_address_missing"
ip rule add priority "$asus_rule_priority" from "$asus_address/32" blackhole
"$controller" monitor
expect_path "tplink_wifi"
remove_rule "$asus_rule_priority"
remove_rule "$wired_rule_priority"
"$controller" monitor
expect_path "wired"
curl -4 --interface enP7s7 --connect-timeout 2 --max-time 5 --silent --show-error --fail --output /dev/null https://1.1.1.1/cdn-cgi/trace
trap - EXIT INT TERM
restore
active_wifi=$(nmcli -g GENERAL.CONNECTION device show wlP9s9)
[ "$active_wifi" = "ds4-uplink-asus" ] || fail "restore_wifi_${active_wifi:-missing}"
echo "uplink_canary_passed wired_to_asus_to_tplink_to_wired=1"
