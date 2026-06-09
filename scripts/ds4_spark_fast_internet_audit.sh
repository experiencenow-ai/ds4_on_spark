#!/usr/bin/env bash
set -euo pipefail

EXPECTED_PUBLIC_IP="${EXPECTED_PUBLIC_IP:-}"
TEST_URL="${TEST_URL:-https://api.ipify.org}"
OUT_DIR="${OUT_DIR:-/private/tmp/ds4_spark_fast_internet_audit}"
LAN_GW="${LAN_GW:-10.20.0.1}"
FALLBACK_GW="${FALLBACK_GW:-10.20.0.13}"
LAN_DEV="${LAN_DEV:-enP7s7}"
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

echo "Mac public IPv4:"
mac_public_ip="$(curl -4 -fsS --connect-timeout 5 --max-time 12 "$TEST_URL" 2>/dev/null || true)"
echo "  ${mac_public_ip:-unknown}"
if [ -z "$EXPECTED_PUBLIC_IP" ]; then
	EXPECTED_PUBLIC_IP="$mac_public_ip"
fi

echo "Mac route to 1.1.1.1:"
route -n get 1.1.1.1 2>/dev/null || true

for pair in "${NODES[@]}"; do
	set -- $pair
	node="$1"
	ip="$2"
	(
		ssh "${SSH_OPTS[@]}" "$node@$ip" "printf 'node=$node\n'; printf 'ip=$ip\n'; printf 'route_get='; ip -4 route get 1.1.1.1 | head -1; printf 'defaults_begin\n'; ip -4 route show default; printf 'defaults_end\n'; printf 'public_ip='; curl -4 -fsS --connect-timeout 5 --max-time 12 '$TEST_URL'; printf '\n'"
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

cat "$OUT_DIR"/*.out
for err in "$OUT_DIR"/*.err; do
	if [ -s "$err" ]; then
		echo "stderr $(basename "$err" .err):"
		cat "$err"
	fi
done

python3 - "$OUT_DIR" "$LAN_GW" "$FALLBACK_GW" "$EXPECTED_PUBLIC_IP" <<'PY'
import glob
import os
import re
import sys

out_dir, lan_gw, fallback_gw, expected_ip = sys.argv[1:5]
rows = []
bad = 0
for path in sorted(glob.glob(os.path.join(out_dir, "*.out"))):
    node = os.path.basename(path).removesuffix(".out")
    text = open(path, "r", encoding="utf-8", errors="replace").read()
    route = re.search(r"^route_get=(.*)$", text, re.M)
    public = re.search(r"^public_ip=(.*)$", text, re.M)
    defaults = re.search(r"defaults_begin\n(.*?)defaults_end", text, re.S)
    route_s = route.group(1).strip() if route else ""
    public_s = public.group(1).strip() if public else ""
    defaults_s = defaults.group(1) if defaults else ""
    fast_ok = f"via {lan_gw} " in route_s
    fallback_ok = node == "spark3" or f"via {fallback_gw} " in defaults_s
    public_ok = True if expected_ip == "" else public_s == expected_ip
    if not (fast_ok and fallback_ok and public_ok):
        bad = 1
    rows.append((node, fast_ok, fallback_ok, public_ok, public_s, route_s))

print("summary:")
print(f"nodes={len(rows)} expected_public_ip={expected_ip or 'not-set'}")
for node, fast_ok, fallback_ok, public_ok, public_s, route_s in rows:
    print(f"{node} fast_default={fast_ok} fallback_default={fallback_ok} public_ip_ok={public_ok} public_ip={public_s or 'missing'} route_get='{route_s}'")
raise SystemExit(bad)
PY
if [ "$status" != "0" ]; then
	exit "$status"
fi
