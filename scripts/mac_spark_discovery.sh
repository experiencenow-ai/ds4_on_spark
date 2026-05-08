#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
usage: mac_spark_discovery.sh [host...]

Runs lightweight macOS-side discovery for Spark hosts:
- Interface snapshots (en0/en1)
- Bonjour SSH browse
- mDNS resolution checks
- TCP/22 reachability probes

Examples:
  ./scripts/mac_spark_discovery.sh
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
	targets="aitopatom-9ab9.local 10.0.0.2 192.168.100.2 192.168.100.10 192.168.100.11"
fi

echo "== meta =="
date -u
echo
echo "== interfaces =="
ifconfig en0 || true
ifconfig en1 || true
echo
echo "== arp =="
arp -a || true
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
	printf "%s:\n" "$host"
	dns-sd -G v4v6 "$host" &
	pid="$!"
	sleep 3
	kill "$pid" >/dev/null 2>&1 || true
	wait "$pid" >/dev/null 2>&1 || true
	echo
done
echo
echo "== known target checks =="
for host in $targets; do
    printf "%s: " "$host"
    nc -vz -G 2 "$host" 22 >/dev/null 2>&1 && echo "ssh reachable" || echo "not reachable"
done
