#!/usr/bin/env bash
set -euo pipefail

MAC_IF="${DS4_MAC_10G_IF:-en0}"
MAC_ADDR="${DS4_MAC_10G_ADDR:-10.20.0.1}"
MAC_MASK="${DS4_MAC_10G_MASK:-255.255.255.0}"
GATEWAY="${DS4_MAC_10G_GATEWAY:-10.20.0.13}"
DEFAULT_ROUTE="${DS4_MAC_10G_DEFAULT_ROUTE:-0}"

run_root()
{
	if [ "$(id -u)" -eq 0 ]
	then
		"$@"
	else
		sudo "$@"
	fi
}

run_root ifconfig "${MAC_IF}" -alias "${MAC_ADDR}" 2>/dev/null || true
run_root ifconfig "${MAC_IF}" inet "${MAC_ADDR}" netmask "${MAC_MASK}" alias
run_root route -n delete -net 0.0.0.0/1 "${GATEWAY}" 2>/dev/null || true
run_root route -n delete -net 128.0.0.0/1 "${GATEWAY}" 2>/dev/null || true
if [ "${DEFAULT_ROUTE}" = "1" ]
then
	run_root route -n add -net 0.0.0.0/1 "${GATEWAY}"
	run_root route -n add -net 128.0.0.0/1 "${GATEWAY}"
	printf 'Mac 10G default route override active: %s=%s/24 via %s\n' "${MAC_IF}" "${MAC_ADDR}" "${GATEWAY}"
else
	printf 'Mac 10G cluster access active: %s=%s/24; default route unchanged\n' "${MAC_IF}" "${MAC_ADDR}"
fi
