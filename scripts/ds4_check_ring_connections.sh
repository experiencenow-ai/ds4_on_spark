#!/usr/bin/env bash
set -euo pipefail

nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
ips=(10.10.100.10 10.10.100.11 10.10.100.12 10.10.100.13 10.10.100.14 10.10.100.15 10.10.100.16 10.10.100.17)
prev_phys=(10.10.16.1 10.10.2.1 10.10.4.1 10.10.6.1 10.10.8.1 10.10.10.1 10.10.12.1 10.10.14.1)
next_phys=(10.10.2.2 10.10.4.2 10.10.6.2 10.10.8.2 10.10.10.2 10.10.12.2 10.10.14.2 10.10.16.2)
prev_dev=(enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0)
next_dev=(enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1)
ssh_opts="${DS4_SSH_OPTS:-}"
fails=0

route_dev()
{
	printf '%s\n' "$1" | awk 'NR == 1 { for (i=1; i<=NF; i++) if ($i == "dev") { print $(i+1); exit } }'
}

fail_probe()
{
	label="$1"
	dst="$2"
	route="$3"
	reason="$4"
	printf 'FAIL %-22s %-13s :: %s :: %s\n' "$label" "$dst" "$reason" "$route"
	fails=$((fails + 1))
}

check_link()
{
	node="$1"
	dev="$2"
	label="$3"
	speed="$(ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout=4 "$node" "cat /sys/class/net/$dev/speed 2>/dev/null" || true)"
	carrier="$(ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout=4 "$node" "cat /sys/class/net/$dev/carrier 2>/dev/null" || true)"
	if [ "$speed" = "200000" ] && [ "$carrier" = "1" ]
	then
		printf 'PASS %-22s %-13s :: speed=%s carrier=%s\n' "$label" "$dev" "$speed" "$carrier"
	else
		fail_probe "$label" "$dev" "" "speed=${speed:-missing} carrier=${carrier:-missing}, expected 200000/1"
	fi
}

probe()
{
	src="$1"
	dst="$2"
	label="$3"
	expected_dev="$4"
	route="$(ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout=4 "$src" "ip route get $dst 2>/dev/null | head -n 1" || true)"
	dev="$(route_dev "$route")"
	if [ "$dev" != "$expected_dev" ]
	then
		fail_probe "$label" "$dst" "$route" "route dev '${dev:-none}', expected '$expected_dev'"
		return
	fi
	case "$dev" in
		wl*|wlan*|en0|eth0)
			fail_probe "$label" "$dst" "$route" "fallback interface '$dev' is forbidden"
			return
			;;
	esac
	if ssh $ssh_opts -o BatchMode=yes -o ConnectTimeout=4 "$src" "ping -c 1 -W 1 $dst >/dev/null" >/dev/null 2>&1
	then
		printf 'PASS %-22s %-13s :: %s\n' "$label" "$dst" "$route"
	else
		fail_probe "$label" "$dst" "$route" "ping failed"
	fi
}

echo "== physical 200G neighbor links =="
for i in 0 1 2 3 4 5 6 7
do
	check_link "${nodes[$i]}" "${prev_dev[$i]}" "${nodes[$i]} prev"
	check_link "${nodes[$i]}" "${next_dev[$i]}" "${nodes[$i]} next"
	probe "${nodes[$i]}" "${prev_phys[$i]}" "${nodes[$i]} prev-phys" "${prev_dev[$i]}"
	probe "${nodes[$i]}" "${next_phys[$i]}" "${nodes[$i]} next-phys" "${next_dev[$i]}"
done

echo "== adjacent loopback ring =="
for i in 0 1 2 3 4 5 6 7
do
	prev=$(((i + 7) % 8))
	next=$(((i + 1) % 8))
	probe "${nodes[$i]}" "${ips[$prev]}" "${nodes[$i]}->${nodes[$prev]}" "${prev_dev[$i]}"
	probe "${nodes[$i]}" "${ips[$next]}" "${nodes[$i]}->${nodes[$next]}" "${next_dev[$i]}"
done

echo "== tcpstore head paths =="
for i in 1 2 3 4 5 6 7
do
	cw=$(((0 - i + 8) % 8))
	ccw=$(((i - 0 + 8) % 8))
	if [ "$cw" -le "$ccw" ]
	then
		expected_dev="${next_dev[$i]}"
	else
		expected_dev="${prev_dev[$i]}"
	fi
	probe "${nodes[$i]}" "${ips[0]}" "${nodes[$i]}->spark0" "$expected_dev"
done
for i in 1 2 3 4 5 6 7
do
	cw=$(((i - 0 + 8) % 8))
	ccw=$(((0 - i + 8) % 8))
	if [ "$cw" -le "$ccw" ]
	then
		expected_dev="${next_dev[0]}"
	else
		expected_dev="${prev_dev[0]}"
	fi
	probe "${nodes[0]}" "${ips[$i]}" "spark0->${nodes[$i]}" "$expected_dev"
done

if [ "$fails" -ne 0 ]
then
	echo "ring connection check failed: $fails failed probes" >&2
	exit 1
fi
echo "ring connection check passed"
