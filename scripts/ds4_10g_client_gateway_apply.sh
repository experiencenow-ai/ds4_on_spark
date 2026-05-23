#!/usr/bin/env bash
set -euo pipefail

CLIENT_IF="${DS4_CLIENT_IF:-enP7s7}"
GATEWAY="${DS4_CLIENT_GATEWAY:-10.20.0.13}"
METRIC="${DS4_CLIENT_METRIC:-50}"
host="$(hostname -s)"

case "${host}" in
	aitopatom-9ab9|spark0)
		addr="10.20.0.10/24"
		;;
	edgexpert-d623|spark1)
		addr="10.20.0.11/24"
		;;
	aitopatom-931a|spark2)
		addr="10.20.0.12/24"
		;;
	aitopatom-a18f|spark3)
		addr="10.20.0.13/24"
		;;
	aitopatom-c342|spark4)
		addr="10.20.0.14/24"
		;;
	aitopatom-a36d|spark5)
		addr="10.20.0.15/24"
		;;
	aitopatom-c637|spark6)
		addr="10.20.0.16/24"
		;;
	thinkstation-pgx|spark7)
		addr="10.20.0.17/24"
		;;
	*)
		printf 'unknown Spark host: %s\n' "${host}" >&2
		exit 2
		;;
esac

ip link set "${CLIENT_IF}" up
ip addr replace "${addr}" dev "${CLIENT_IF}"
if ping -c 1 -W 1 -I "${CLIENT_IF}" "${GATEWAY}" >/dev/null 2>&1
then
	ip route replace default via "${GATEWAY}" dev "${CLIENT_IF}" metric "${METRIC}"
	printf 'ds4 10G client default route active: %s via %s metric %s\n' "${CLIENT_IF}" "${GATEWAY}" "${METRIC}"
else
	printf 'gateway %s is not reachable on %s; leaving existing default routes unchanged\n' "${GATEWAY}" "${CLIENT_IF}" >&2
	exit 3
fi
