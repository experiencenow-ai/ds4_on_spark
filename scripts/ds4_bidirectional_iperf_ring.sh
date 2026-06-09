#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-/private/tmp/ds4_bidirectional_iperf_ring}"
PORT_BASE="${PORT_BASE:-5720}"
DURATION="${DURATION:-8}"
PARALLEL="${PARALLEL:-8}"
OMIT="${OMIT:-1}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-8}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT")

EDGES=(
	"spark0 spark1 10.10.1.2 10.10.1.1 spark0_spark1"
	"spark1 spark2 10.10.3.2 10.10.3.1 spark1_spark2"
	"spark2 spark3 10.10.5.2 10.10.5.1 spark2_spark3"
	"spark3 spark4 10.10.7.2 10.10.7.1 spark3_spark4"
	"spark4 spark5 10.10.9.2 10.10.9.1 spark4_spark5"
	"spark5 spark6 10.10.11.2 10.10.11.1 spark5_spark6"
	"spark6 spark7 10.10.13.2 10.10.13.1 spark6_spark7"
	"spark7 spark8 10.10.16.2 10.10.16.1 spark7_spark8"
	"spark8 spark9 10.10.18.2 10.10.18.1 spark8_spark9"
	"spark9 sparka 10.10.20.2 10.10.20.1 spark9_sparka"
	"sparka sparkb 10.10.22.2 10.10.22.1 sparka_sparkb"
	"sparkb sparkc 10.10.24.2 10.10.24.1 sparkb_sparkc"
	"sparkc spark0 10.10.26.2 10.10.26.1 sparkc_spark0"
)

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

port="$PORT_BASE"
for edge in "${EDGES[@]}"; do
	set -- $edge
	left="$1"
	right="$2"
	right_ip="$3"
	left_ip="$4"
	label="$5"
	fwd_port="$port"
	rev_port="$((port + 1000))"
	echo "$left $right $right_ip $left_ip $label $fwd_port $rev_port" >> "$OUT_DIR/edges.txt"
	ssh "${SSH_OPTS[@]}" "$right" "nohup iperf3 -s -1 -B '$right_ip' -p '$fwd_port' >/tmp/ds4-bidir-iperf-${fwd_port}.log 2>&1 < /dev/null &"
	ssh "${SSH_OPTS[@]}" "$left" "nohup iperf3 -s -1 -B '$left_ip' -p '$rev_port' >/tmp/ds4-bidir-iperf-${rev_port}.log 2>&1 < /dev/null &"
	port=$((port + 1))
done

sleep 1
start_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
while read -r left right right_ip left_ip label fwd_port rev_port; do
	(
		ssh "${SSH_OPTS[@]}" "$left" "iperf3 -c '$right_ip' -p '$fwd_port' -t '$DURATION' -O '$OMIT' -P '$PARALLEL' -Z"
	) > "$OUT_DIR/${label}_cw.out" 2> "$OUT_DIR/${label}_cw.err" &
	echo "$!" > "$OUT_DIR/${label}_cw.pid"
	(
		ssh "${SSH_OPTS[@]}" "$right" "iperf3 -c '$left_ip' -p '$rev_port' -t '$DURATION' -O '$OMIT' -P '$PARALLEL' -Z"
	) > "$OUT_DIR/${label}_ccw.out" 2> "$OUT_DIR/${label}_ccw.err" &
	echo "$!" > "$OUT_DIR/${label}_ccw.pid"
done < "$OUT_DIR/edges.txt"

status=0
while read -r left right right_ip left_ip label fwd_port rev_port; do
	for direction in cw ccw; do
		pid="$(cat "$OUT_DIR/${label}_${direction}.pid")"
		if ! wait "$pid"; then
			status=1
		fi
	done
done < "$OUT_DIR/edges.txt"
end_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"

while read -r left right right_ip left_ip label fwd_port rev_port; do
	for direction in cw ccw; do
		out="$OUT_DIR/${label}_${direction}.out"
		err="$OUT_DIR/${label}_${direction}.err"
		if [ -s "$out" ]; then
			echo "OK ${label}_${direction}"
		else
			echo "FAIL ${label}_${direction} no-output"
		fi
		if [ -s "$err" ]; then
			echo "stderr ${label}_${direction}:"
			cat "$err"
		fi
	done
done < "$OUT_DIR/edges.txt"

python3 - "$OUT_DIR" "$start_ms" "$end_ms" <<'PY'
import glob
import os
import re
import statistics
import sys

out_dir, start_ms, end_ms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
mult = {
    "bits/sec": 1.0,
    "Kbits/sec": 1e3,
    "Mbits/sec": 1e6,
    "Gbits/sec": 1e9,
}
rows = []
for path in sorted(glob.glob(os.path.join(out_dir, "*.out"))):
    label = os.path.basename(path).removesuffix(".out")
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    found = None
    for line in text.splitlines():
        if "[SUM]" in line and "sender" in line:
            found = line
    if found is None:
        rows.append((label, 0.0, "no-sum"))
        continue
    match = re.search(r"([0-9.]+)\s+([KMG]?bits/sec)\s+(?:[0-9]+\s+)?sender\b", found)
    if match is None:
        rows.append((label, 0.0, found.strip()))
        continue
    value = float(match.group(1))
    unit = match.group(2)
    rows.append((label, value * mult[unit], f"{value:g} {unit}"))

bps_values = [row[1] for row in rows if row[1] > 0]
total_bps = sum(row[1] for row in rows)
wall_s = max((end_ms - start_ms) / 1000.0, 0.001)
pair_totals = {}
for label, bps, display in rows:
    if label.endswith("_cw"):
        pair = label.removesuffix("_cw")
    elif label.endswith("_ccw"):
        pair = label.removesuffix("_ccw")
    else:
        pair = label
    pair_totals[pair] = pair_totals.get(pair, 0.0) + bps
print("summary:")
print(f"directions={len(rows)} edges={len(rows) // 2} duration_s_env={os.environ.get('DURATION', '8')} parallel_streams_env={os.environ.get('PARALLEL', '8')}")
print(f"wall_time_s={wall_s:.3f}")
print(f"sum_sender_Gbps={total_bps / 1e9:.3f}")
if bps_values:
    print(f"min_direction_Gbps={min(bps_values) / 1e9:.3f}")
    print(f"median_direction_Gbps={statistics.median(bps_values) / 1e9:.3f}")
    print(f"max_direction_Gbps={max(bps_values) / 1e9:.3f}")
for label, bps, display in rows:
    print(f"{label}_Gbps={bps / 1e9:.3f} raw={display}")
for pair in sorted(pair_totals):
    print(f"{pair}_bidirectional_total_Gbps={pair_totals[pair] / 1e9:.3f}")
PY

echo "Output dir: $OUT_DIR"
exit "$status"
