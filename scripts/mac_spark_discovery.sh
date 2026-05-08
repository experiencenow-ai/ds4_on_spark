#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: mac_spark_discovery.sh [host...]

Runs lightweight macOS-side discovery for Spark hosts:
- Interface snapshots (en0/en1, no MAC addresses)
- ARP table (MACs stripped)
- Bonjour SSH browse
- Optional mDNS resolution checks for *.local targets
- TCP/22 reachability probes

Environment:
  REDACT=1   Redact IPv4/IPv6/MAC addresses from output

Examples:
  ./scripts/mac_spark_discovery.sh
  REDACT=1 ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local spark1.local
  ./scripts/mac_spark_discovery.sh aitopatom-9ab9.local 10.0.0.2
EOF
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

if [ "$#" -gt 0 ]; then
	targets="$*"
else
	targets="aitopatom-9ab9.local spark1.local"
fi

tmp="$(mktemp /private/tmp/ds4_mac_spark_discovery.XXXXXX)"
trap 'rm -f "$tmp"' EXIT INT HUP TERM

{
echo "== meta =="
date -u
echo
echo "== interfaces =="
for iface in en0 en1; do
	echo "-- $iface --"
	ifconfig "$iface" 2>/dev/null | awk '
		/^[[:space:]]*status:/ { print; next }
		/^[[:space:]]*mtu/ { print; next }
		/^[[:space:]]*inet / { print; next }
		/^[[:space:]]*inet6 / { print; next }
	' || true
done
echo
echo "== arp =="
arp -an 2>/dev/null | sed -E 's/ at [^ ]+ on / on /' || true
echo
echo "== ssh service browse, 5 seconds =="
dns-sd -B _ssh._tcp local &
pid="$!"
sleep 5
kill "$pid" >/dev/null 2>&1 || true
wait "$pid" >/dev/null 2>&1 || true
echo
echo "== mdns resolution, 3 seconds each =="
for host in $targets; do
	case "$host" in
		*.local)
			echo "-- $host --"
			dns-sd -G v4v6 "$host" &
			pid="$!"
			sleep 3
			kill "$pid" >/dev/null 2>&1 || true
			wait "$pid" >/dev/null 2>&1 || true
			;;
		*)
			;;
	esac
done
echo
echo "== known target checks =="
for host in $targets; do
	printf "%s: " "$host"
	nc -vz -G 2 "$host" 22 >/dev/null 2>&1 && echo "ssh reachable" || echo "not reachable"
done
} >"$tmp"

if [ "${REDACT:-0}" = "1" ]; then
	sed -E \
		-e 's/([0-9]{1,3}[.]){3}[0-9]{1,3}/<redacted-ipv4>/g' \
		-e 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/<redacted-mac>/g' \
		-e 's/([0-9A-Fa-f]{0,4}:){3,7}[0-9A-Fa-f]{0,4}/<redacted-ipv6>/g' \
		"$tmp"
else
	cat "$tmp"
fi
