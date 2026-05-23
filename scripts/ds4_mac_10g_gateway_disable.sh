#!/usr/bin/env bash
set -euo pipefail

MAC_IF="${DS4_MAC_10G_IF:-en0}"
MAC_ADDR="${DS4_MAC_10G_ADDR:-10.20.0.1}"
GATEWAY="${DS4_MAC_10G_GATEWAY:-10.20.0.13}"
REMOVE_ALIAS="${DS4_MAC_10G_REMOVE_ALIAS:-0}"

run_root()
{
	if [ "$(id -u)" -eq 0 ]
	then
		"$@"
	else
		sudo "$@"
	fi
}

run_root route -n delete -net 0.0.0.0/1 "${GATEWAY}" 2>/dev/null || true
run_root route -n delete -net 128.0.0.0/1 "${GATEWAY}" 2>/dev/null || true
if [ "${REMOVE_ALIAS}" = "1" ]
then
	run_root ifconfig "${MAC_IF}" -alias "${MAC_ADDR}" 2>/dev/null || true
	printf 'Mac 10G route override disabled and %s alias removed from %s\n' "${MAC_ADDR}" "${MAC_IF}"
else
	printf 'Mac 10G route override disabled; %s alias left on %s\n' "${MAC_ADDR}" "${MAC_IF}"
fi
