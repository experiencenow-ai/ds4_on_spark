#!/usr/bin/env sh
set -eu

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
echo "== known target checks =="
for host in aitopatom-9ab9.local 10.0.0.2 192.168.100.2 192.168.100.10 192.168.100.11; do
    printf "%s: " "$host"
    nc -vz -G 2 "$host" 22 >/dev/null 2>&1 && echo "ssh reachable" || echo "not reachable"
done

