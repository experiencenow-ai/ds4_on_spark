#!/usr/bin/env bash
set -euo pipefail

nodes=(spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7)
ips=(10.10.100.10 10.10.100.11 10.10.100.12 10.10.100.13 10.10.100.14 10.10.100.15 10.10.100.16 10.10.100.17)
p2_f0=(10.10.16.2 10.10.2.2 10.10.4.2 10.10.6.2 10.10.8.2 10.10.10.2 10.10.12.2 10.10.14.2)
p2_f1=(10.10.2.1 10.10.4.1 10.10.6.1 10.10.8.1 10.10.10.1 10.10.12.1 10.10.14.1 10.10.16.1)
prev_phys=(10.10.16.1 10.10.2.1 10.10.4.1 10.10.6.1 10.10.8.1 10.10.10.1 10.10.12.1 10.10.14.1)
next_phys=(10.10.2.2 10.10.4.2 10.10.6.2 10.10.8.2 10.10.10.2 10.10.12.2 10.10.14.2 10.10.16.2)
prev_dev=(enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0 enP2p1s0f0np0)
next_dev=(enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1 enP2p1s0f1np1)
ssh_opts="${DS4_SSH_OPTS:-}"
topology="${DS4_FABRIC_TOPOLOGY:-line}"
fails=0

expected_direction()
{
	src="$1"
	dst="$2"
	if [ "$topology" = "line" ]
	then
		if [ "$dst" -gt "$src" ]
		then
			printf 'next\n'
		else
			printf 'prev\n'
		fi
		return
	fi
	cw=$(((dst - src + 8) % 8))
	ccw=$(((src - dst + 8) % 8))
	if [ "$cw" -le "$ccw" ]
	then
		printf 'next\n'
	else
		printf 'prev\n'
	fi
}

expected_dev_for()
{
	src="$1"
	dst="$2"
	dir="$(expected_direction "$src" "$dst")"
	if [ "$dir" = "next" ]
	then
		printf '%s\n' "${next_dev[$src]}"
	else
		printf '%s\n' "${prev_dev[$src]}"
	fi
}

endpoint_exists()
{
	node_index="$1"
	addr="$2"
	if [ "$topology" != "line" ]
	then
		return 0
	fi
	if [ "$node_index" -eq 0 ] && [ "$addr" = "${p2_f0[0]}" ]
	then
		return 1
	fi
	if [ "$node_index" -eq 7 ] && [ "$addr" = "${p2_f1[7]}" ]
	then
		return 1
	fi
	return 0
}

if [ "$topology" != "line" ] && [ "$topology" != "ring" ]
then
	echo "DS4_FABRIC_TOPOLOGY must be line or ring, got '$topology'" >&2
	exit 2
fi

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
	if [ "$topology" = "ring" ] || [ "$i" -gt 0 ]
	then
		check_link "${nodes[$i]}" "${prev_dev[$i]}" "${nodes[$i]} prev"
		probe "${nodes[$i]}" "${prev_phys[$i]}" "${nodes[$i]} prev-phys" "${prev_dev[$i]}"
	fi
	if [ "$topology" = "ring" ] || [ "$i" -lt 7 ]
	then
		check_link "${nodes[$i]}" "${next_dev[$i]}" "${nodes[$i]} next"
		probe "${nodes[$i]}" "${next_phys[$i]}" "${nodes[$i]} next-phys" "${next_dev[$i]}"
	fi
done

echo "== adjacent loopback $topology =="
for i in 0 1 2 3 4 5 6 7
do
	if [ "$topology" = "ring" ] || [ "$i" -gt 0 ]
	then
		prev=$(((i + 7) % 8))
		probe "${nodes[$i]}" "${ips[$prev]}" "${nodes[$i]}->${nodes[$prev]}" "${prev_dev[$i]}"
	fi
	if [ "$topology" = "ring" ] || [ "$i" -lt 7 ]
	then
		next=$(((i + 1) % 8))
		probe "${nodes[$i]}" "${ips[$next]}" "${nodes[$i]}->${nodes[$next]}" "${next_dev[$i]}"
	fi
done

echo "== routed physical 200G endpoints =="
for i in 0 1 2 3 4 5 6 7
do
	for j in 0 1 2 3 4 5 6 7
	do
		if [ "$i" -eq "$j" ]
		then
			continue
		fi
		expected_dev="$(expected_dev_for "$i" "$j")"
		for dst in "${p2_f0[$j]}" "${p2_f1[$j]}"
		do
			if ! endpoint_exists "$j" "$dst"
			then
				continue
			fi
			if [ "$dst" = "${prev_phys[$i]}" ] || [ "$dst" = "${next_phys[$i]}" ]
			then
				continue
			fi
			probe "${nodes[$i]}" "$dst" "${nodes[$i]}->${nodes[$j]}-p2" "$expected_dev"
		done
	done
done

echo "== tcpstore head paths =="
for i in 1 2 3 4 5 6 7
do
	expected_dev="$(expected_dev_for "$i" 0)"
	probe "${nodes[$i]}" "${ips[0]}" "${nodes[$i]}->spark0" "$expected_dev"
done
for i in 1 2 3 4 5 6 7
do
	expected_dev="$(expected_dev_for 0 "$i")"
	probe "${nodes[0]}" "${ips[$i]}" "spark0->${nodes[$i]}" "$expected_dev"
done

if [ "$fails" -ne 0 ]
then
	echo "$topology connection check failed: $fails failed probes" >&2
	exit 1
fi
echo "$topology connection check passed"
