#!/usr/bin/env bash
set -euo pipefail

PORT_BASE="${PORT_BASE:-5840}"
RUNS="${RUNS:-5}"
OUT_DIR="${OUT_DIR:-/private/tmp/ds4_pipeline_ring_latency}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-8}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT")

EDGES=(
	"spark0 spark1 10.10.1.2 spark0_to_spark1"
	"spark1 spark2 10.10.3.2 spark1_to_spark2"
	"spark2 spark3 10.10.5.2 spark2_to_spark3"
	"spark3 spark4 10.10.7.2 spark3_to_spark4"
	"spark4 spark5 10.10.9.2 spark4_to_spark5"
	"spark5 spark6 10.10.11.2 spark5_to_spark6"
	"spark6 spark7 10.10.13.2 spark6_to_spark7"
	"spark7 spark8 10.10.16.2 spark7_to_spark8"
	"spark8 spark9 10.10.18.2 spark8_to_spark9"
	"spark9 sparka 10.10.20.2 spark9_to_sparka"
	"sparka sparkb 10.10.22.2 sparka_to_sparkb"
	"sparkb sparkc 10.10.24.2 sparkb_to_sparkc"
	"sparkc spark0 10.10.26.2 sparkc_to_spark0"
)

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

python_forwarder='
import socket
import sys

listen_ip = sys.argv[1]
listen_port = int(sys.argv[2])
next_ip = sys.argv[3]
next_port = int(sys.argv[4])

out = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
out.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
out.connect((next_ip, next_port))

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((listen_ip, listen_port))
srv.listen(1)
conn, _ = srv.accept()
conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

while True:
	data = conn.recv(65536)
	if not data:
		break
	out.sendall(data)
try:
	out.shutdown(socket.SHUT_WR)
except OSError:
	pass
conn.close()
out.close()
srv.close()
'

python_receiver='
import socket
import sys
import time

listen_ip = sys.argv[1]
listen_port = int(sys.argv[2])
stamp_path = sys.argv[3]

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((listen_ip, listen_port))
srv.listen(1)
conn, _ = srv.accept()
conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
data = conn.recv(1)
recv_ns = time.monotonic_ns()
with open(stamp_path, "w", encoding="utf-8") as handle:
	handle.write(str(recv_ns) + "\n")
conn.close()
srv.close()
'

python_sender='
import socket
import sys
import time

target_ip = sys.argv[1]
target_port = int(sys.argv[2])

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
s.connect((target_ip, target_port))
send_ns = time.monotonic_ns()
s.sendall(b"x")
try:
	s.shutdown(socket.SHUT_WR)
except OSError:
	pass
s.close()
print(send_ns)
'

run_once()
{
	local run="$1"
	local port_base="$2"
	local recv_file send_ns recv_ns latency_us listen_node listen_ip listen_port next_ip next_port label i edge
	recv_file="/tmp/ds4_pipeline_ring_recv_${port_base}.txt"
	ssh "${SSH_OPTS[@]}" spark0 "rm -f '$recv_file'; nohup python3 -c '$python_receiver' 10.10.26.2 '$((port_base + 12))' '$recv_file' >/tmp/ds4-pipeline-recv-${port_base}.log 2>&1 < /dev/null &"
	sleep 0.2
	for ((i=${#EDGES[@]}-2; i>=0; i--)); do
		edge="${EDGES[$i]}"
		set -- $edge
		listen_node="$2"
		listen_ip="$3"
		label="$4"
		listen_port="$((port_base + i))"
		set -- ${EDGES[$((i + 1))]}
		next_ip="$3"
		next_port="$((port_base + i + 1))"
		ssh "${SSH_OPTS[@]}" "$listen_node" "nohup python3 -c '$python_forwarder' '$listen_ip' '$listen_port' '$next_ip' '$next_port' >/tmp/ds4-pipeline-${label}-${port_base}.log 2>&1 < /dev/null &"
		sleep 0.1
	done
	sleep 0.5
	send_ns="$(ssh "${SSH_OPTS[@]}" spark0 "python3 -c '$python_sender' 10.10.1.2 '$port_base'")"
	for _ in $(seq 1 50); do
		recv_ns="$(ssh "${SSH_OPTS[@]}" spark0 "cat '$recv_file' 2>/dev/null || true")"
		if [ -n "$recv_ns" ]; then
			break
		fi
		sleep 0.1
	done
	if [ -z "${recv_ns:-}" ]; then
		echo "run=$run status=timeout"
		return 1
	fi
	latency_us="$(python3 - "$send_ns" "$recv_ns" <<'PY'
import sys
send_ns = int(sys.argv[1])
recv_ns = int(sys.argv[2])
print(f"{(recv_ns - send_ns) / 1000.0:.3f}")
PY
)"
	echo "run=$run send_ns=$send_ns recv_ns=$recv_ns latency_us=$latency_us"
}

status=0
for run in $(seq 1 "$RUNS"); do
	if ! run_once "$run" "$((PORT_BASE + (run * 32)))" | tee "$OUT_DIR/run_${run}.txt"; then
		status=1
	fi
done

python3 - "$OUT_DIR" <<'PY'
import glob
import re
import statistics
import sys

vals = []
for path in sorted(glob.glob(sys.argv[1] + "/run_*.txt")):
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    match = re.search(r"latency_us=([0-9.]+)", text)
    if match:
        vals.append(float(match.group(1)))

if not vals:
    print("summary: no successful runs")
    raise SystemExit(1)

print("summary:")
print(f"runs={len(vals)}")
print(f"min_us={min(vals):.3f}")
print(f"median_us={statistics.median(vals):.3f}")
print(f"max_us={max(vals):.3f}")
print(f"mean_us={statistics.mean(vals):.3f}")
PY

echo "Output dir: $OUT_DIR"
exit "$status"

