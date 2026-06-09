#!/usr/bin/env bash
set -euo pipefail

BYTES="${BYTES:-75000000}"
URL="${URL:-https://speed.cloudflare.com/__down?bytes=$BYTES}"
OUT_DIR="${OUT_DIR:-/private/tmp/ds4_parallel_internet_download}"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-8}"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_transfer_known_hosts)
NODES=(
	"spark0 10.20.0.10"
	"spark1 10.20.0.11"
	"spark2 10.20.0.12"
	"spark3 10.20.0.13"
	"spark4 10.20.0.14"
	"spark5 10.20.0.15"
	"spark6 10.20.0.16"
	"spark7 10.20.0.17"
	"spark8 10.20.0.18"
	"spark9 10.20.0.19"
	"sparka 10.20.0.20"
	"sparkb 10.20.0.21"
	"sparkc 10.20.0.22"
)

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

start_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
for pair in "${NODES[@]}"; do
	set -- $pair
	node="$1"
	ip="$2"
	(
		ssh "${SSH_OPTS[@]}" "$node@$ip" "curl -4 -L -o /dev/null -sS --connect-timeout 5 --max-time 30 -w 'node=$node http_code=%{http_code} remote_ip=%{remote_ip} time_connect=%{time_connect} time_starttransfer=%{time_starttransfer} time_total=%{time_total} size_download=%{size_download} speed_download=%{speed_download}\n' '$URL'"
	) > "$OUT_DIR/$node.out" 2> "$OUT_DIR/$node.err" &
	echo "$!" > "$OUT_DIR/$node.pid"
done

status=0
for pair in "${NODES[@]}"; do
	set -- $pair
	node="$1"
	pid="$(cat "$OUT_DIR/$node.pid")"
	if ! wait "$pid"; then
		status=1
	fi
done
end_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"

cat "$OUT_DIR"/*.out
for err in "$OUT_DIR"/*.err; do
	if [ -s "$err" ]; then
		echo "stderr $(basename "$err" .err):"
		cat "$err"
	fi
done

python3 - "$OUT_DIR" "$start_ms" "$end_ms" "$BYTES" <<'PY'
import glob
import os
import sys

out_dir, start_ms, end_ms, requested = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
rows = []
for path in sorted(glob.glob(os.path.join(out_dir, "*.out"))):
    text = open(path, "r", encoding="utf-8", errors="replace").read().strip()
    if text == "":
        continue
    fields = {}
    for item in text.split():
        if "=" in item:
            key, value = item.split("=", 1)
            fields[key] = value
    try:
        fields["size_download"] = int(float(fields.get("size_download", "0")))
        fields["speed_download"] = float(fields.get("speed_download", "0"))
        fields["time_total"] = float(fields.get("time_total", "0"))
    except ValueError:
        pass
    rows.append(fields)

total_bytes = sum(int(r.get("size_download", 0)) for r in rows)
wall_s = max((end_ms - start_ms) / 1000.0, 0.001)
sum_bps = sum(float(r.get("speed_download", 0)) for r in rows)
print("summary:")
print(f"nodes={len(rows)} bytes_per_node_requested={requested}")
print(f"total_downloaded_bytes={total_bytes}")
print(f"wall_time_s={wall_s:.3f}")
print(f"aggregate_wall_Bps={total_bytes / wall_s:.0f}")
print(f"aggregate_wall_Gbps={(total_bytes * 8 / wall_s) / 1e9:.3f}")
print(f"sum_reported_Bps={sum_bps:.0f}")
print(f"sum_reported_Gbps={(sum_bps * 8) / 1e9:.3f}")
for r in rows:
    node = r.get("node", "?")
    speed = float(r.get("speed_download", 0))
    print(f"{node}_Gbps={(speed * 8) / 1e9:.3f} time_s={float(r.get('time_total', 0)):.3f} http={r.get('http_code', '?')} remote_ip={r.get('remote_ip', '?')}")
PY

exit "$status"

