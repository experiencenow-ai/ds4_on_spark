#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${OUT_DIR:-/private/tmp/ds4_dual_rail_iperf_ring}"
PORT_BASE="${PORT_BASE:-5920}"
DURATION="${DURATION:-8}"
PARALLEL="${PARALLEL:-8}"
OMIT="${OMIT:-1}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-8}"
TOPOLOGY="${TOPOLOGY:-v2/profiles/transfer/spark_200g.json}"
SSH_OPTS=(-n -o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT")

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

python3 - "$TOPOLOGY" > "$OUT_DIR/rails.txt" <<'PY'
import json
import sys

topology = json.load(open(sys.argv[1], "r", encoding="utf-8"))
ring = ["spark0", "spark1", "spark2", "spark3", "spark4", "spark5", "spark6", "spark7", "spark8", "spark9", "sparka", "sparkb", "sparkc", "spark0"]
edges = {(edge["source_node"], edge["destination_node"]): edge["rails"] for edge in topology.get("fabric_edges", [])}
for left, right in zip(ring, ring[1:]):
    rails = edges.get((left, right), [])
    if len(rails) < 2:
        raise SystemExit(f"missing dual rails for {left}->{right}")
    for index, rail in enumerate(rails):
        print(left, right, rail["source_ip"], rail["destination_ip"], f"{left}_{right}_{rail.get('name') or f'r{index}'}")
PY

port="$PORT_BASE"
while read -r src dst src_ip dst_ip label; do
	echo "$src $dst $src_ip $dst_ip $label $port" >> "$OUT_DIR/run.txt"
	ssh "${SSH_OPTS[@]}" "$dst" "nohup iperf3 -s -1 -B '$dst_ip' -p '$port' >/tmp/ds4-dual-rail-iperf-$port.log 2>&1 < /dev/null &"
	port=$((port + 1))
done < "$OUT_DIR/rails.txt"

sleep 1
start_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
while read -r src dst src_ip dst_ip label port; do
	(
		ssh "${SSH_OPTS[@]}" "$src" "iperf3 -c '$dst_ip' -B '$src_ip' -p '$port' -t '$DURATION' -O '$OMIT' -P '$PARALLEL' -Z"
	) > "$OUT_DIR/$label.out" 2> "$OUT_DIR/$label.err" &
	echo "$!" > "$OUT_DIR/$label.pid"
done < "$OUT_DIR/run.txt"

status=0
while read -r src dst src_ip dst_ip label port; do
	pid="$(cat "$OUT_DIR/$label.pid")"
	if ! wait "$pid"; then
		status=1
	fi
done < "$OUT_DIR/run.txt"
end_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"

while read -r src dst src_ip dst_ip label port; do
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
done < "$OUT_DIR/run.txt"

python3 - "$OUT_DIR" "$start_ms" "$end_ms" <<'PY'
import glob
import os
import re
import statistics
import sys

out_dir, start_ms, end_ms = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
mult = {"bits/sec": 1.0, "Kbits/sec": 1e3, "Mbits/sec": 1e6, "Gbits/sec": 1e9}
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

edge_totals = {}
for label, bps, display in rows:
    edge = label.rsplit("_r", 1)[0]
    edge_totals[edge] = edge_totals.get(edge, 0.0) + bps
bps_values = [row[1] for row in rows if row[1] > 0]
edge_values = [value for value in edge_totals.values() if value > 0]
total_bps = sum(row[1] for row in rows)
wall_s = max((end_ms - start_ms) / 1000.0, 0.001)
print("summary:")
print(f"rails={len(rows)} edges={len(edge_totals)} duration_s_env={os.environ.get('DURATION', '8')} parallel_streams_env={os.environ.get('PARALLEL', '8')}")
print(f"wall_time_s={wall_s:.3f}")
print(f"sum_sender_Gbps={total_bps / 1e9:.3f}")
if bps_values:
    print(f"min_rail_Gbps={min(bps_values) / 1e9:.3f}")
    print(f"median_rail_Gbps={statistics.median(bps_values) / 1e9:.3f}")
    print(f"max_rail_Gbps={max(bps_values) / 1e9:.3f}")
if edge_values:
    print(f"min_edge_total_Gbps={min(edge_values) / 1e9:.3f}")
    print(f"median_edge_total_Gbps={statistics.median(edge_values) / 1e9:.3f}")
    print(f"max_edge_total_Gbps={max(edge_values) / 1e9:.3f}")
for label, bps, display in rows:
    print(f"{label}_Gbps={bps / 1e9:.3f} raw={display}")
for edge in sorted(edge_totals):
    print(f"{edge}_dual_rail_total_Gbps={edge_totals[edge] / 1e9:.3f}")
PY

echo "Output dir: $OUT_DIR"
exit "$status"
