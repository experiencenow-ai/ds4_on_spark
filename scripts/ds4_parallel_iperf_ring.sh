#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-/private/tmp/ds4_parallel_iperf_ring}"
PORT_BASE="${PORT_BASE:-5620}"
DURATION="${DURATION:-8}"
PARALLEL="${PARALLEL:-8}"
OMIT="${OMIT:-1}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-8}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT")

EDGES=(
	"spark0 spark1 10.10.1.2 spark0->spark1_r1"
	"spark1 spark2 10.10.3.2 spark1->spark2_r1"
	"spark2 spark3 10.10.5.2 spark2->spark3_r1"
	"spark3 spark4 10.10.7.2 spark3->spark4_r1"
	"spark4 spark5 10.10.9.2 spark4->spark5_r1"
	"spark5 spark6 10.10.11.2 spark5->spark6_r1"
	"spark6 spark7 10.10.13.2 spark6->spark7_r1"
	"spark7 spark8 10.10.16.2 spark7->spark8"
	"spark8 spark9 10.10.18.2 spark8->spark9"
	"spark9 sparka 10.10.20.2 spark9->sparka"
	"sparka sparkb 10.10.22.2 sparka->sparkb"
	"sparkb sparkc 10.10.24.2 sparkb->sparkc"
	"sparkc spark0 10.10.26.2 sparkc->spark0"
)

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

port="$PORT_BASE"
for edge in "${EDGES[@]}"; do
	set -- $edge
	src="$1"
	dst="$2"
	target="$3"
	label="$4"
	echo "$src $dst $target $label $port" >> "$OUT_DIR/edges.txt"
	ssh "${SSH_OPTS[@]}" "$dst" "nohup iperf3 -s -1 -B '$target' -p '$port' >/tmp/ds4-parallel-iperf-$port.log 2>&1 < /dev/null &"
	port=$((port + 1))
done

sleep 1
start_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
while read -r src dst target label port; do
	(
		ssh "${SSH_OPTS[@]}" "$src" "iperf3 -c '$target' -p '$port' -t '$DURATION' -O '$OMIT' -P '$PARALLEL' -Z"
	) > "$OUT_DIR/$label.out" 2> "$OUT_DIR/$label.err" &
	echo "$!" > "$OUT_DIR/$label.pid"
done < "$OUT_DIR/edges.txt"

status=0
while read -r src dst target label port; do
	pid="$(cat "$OUT_DIR/$label.pid")"
	if ! wait "$pid"; then
		status=1
	fi
done < "$OUT_DIR/edges.txt"
end_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"

while read -r src dst target label port; do
	out="$OUT_DIR/$label.out"
	err="$OUT_DIR/$label.err"
	if [ -s "$out" ]; then
		echo "OK $label"
	else
		echo "FAIL $label no-output"
	fi
	if [ -s "$err" ]; then
		echo "stderr $label:"
		cat "$err"
	fi
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
print("summary:")
print(f"edges={len(rows)} duration_s_env={os.environ.get('DURATION', '8')} parallel_streams_env={os.environ.get('PARALLEL', '8')}")
print(f"wall_time_s={wall_s:.3f}")
print(f"sum_sender_Gbps={total_bps / 1e9:.3f}")
if bps_values:
    print(f"min_edge_Gbps={min(bps_values) / 1e9:.3f}")
    print(f"median_edge_Gbps={statistics.median(bps_values) / 1e9:.3f}")
    print(f"max_edge_Gbps={max(bps_values) / 1e9:.3f}")
for label, bps, display in rows:
    print(f"{label}_Gbps={bps / 1e9:.3f} raw={display}")
PY

echo "Output dir: $OUT_DIR"
exit "$status"

