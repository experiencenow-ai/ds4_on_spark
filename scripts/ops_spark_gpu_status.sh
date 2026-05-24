#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_spark_gpu_status.sh -- ring-wide Spark GPU utilization snapshot

Usage:
  ops_spark_gpu_status.sh [--inventory-file <path>] [--jsonl <path>] [target ...]
  ops_spark_gpu_status.sh [--watch --interval N --count N] [--inventory-file <path>] [target ...]

Notes:
  - Defaults to SSH aliases spark0 ... spark7 when no targets or inventory are given.
  - Prints utilization.gpu as gpu_used_pct and utilization.memory as memory_used_pct.
  - On GB10 unified-memory hosts, nvidia-smi may report memory.total/used as N/A.
EOF
}

inventory_file=""
jsonl=""
watch=0
interval=5
count=1

while [ $# -gt 0 ]; do
	case "$1" in
		--inventory-file)
			inventory_file="${2:-}"
			shift 2
			;;
		--jsonl)
			jsonl="${2:-}"
			shift 2
			;;
		--watch)
			watch=1
			count=0
			shift
			;;
		--interval)
			interval="${2:-}"
			shift 2
			;;
		--count)
			count="${2:-}"
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			break
			;;
	esac
done

case "$interval" in
	''|*[!0-9]*)
		echo "invalid --interval: $interval" >&2
		exit 2
		;;
esac

case "$count" in
	''|*[!0-9]*)
		echo "invalid --count: $count" >&2
		exit 2
		;;
esac

if [ "$inventory_file" != "" ]; then
	if [ ! -f "$inventory_file" ]; then
		echo "inventory file not found: $inventory_file" >&2
		exit 2
	fi
	while IFS= read -r line || [ "$line" != "" ]; do
		case "$line" in
			""|\#*)
				continue
				;;
		esac
		set -- "$@" "$line"
	done < "$inventory_file"
fi

if [ "$#" -eq 0 ]; then
	set -- spark0 spark1 spark2 spark3 spark4 spark5 spark6 spark7
fi

SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new}"

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

emit_jsonl()
{
	if [ "$jsonl" = "" ]; then
		return 0
	fi
	target="$1"
	node="$2"
	host="$3"
	utc="$4"
	gpu="$5"
	name="$6"
	gpu_pct="$7"
	mem_pct="$8"
	mem_total="$9"
	shift 9
	mem_used="$1"
	power_w="$2"
	clock_sm="$3"
	pstate="$4"
	python3 - "$jsonl" "$target" "$node" "$host" "$utc" "$gpu" "$name" "$gpu_pct" "$mem_pct" "$mem_total" "$mem_used" "$power_w" "$clock_sm" "$pstate" <<'PY'
import json
import sys

path = sys.argv[1]
keys = ["target", "node", "host", "utc", "gpu_index", "gpu_name", "gpu_used_pct", "memory_used_pct", "memory_total_mib", "memory_used_mib", "power_w", "clocks_sm_mhz", "pstate"]
rec = dict(zip(keys, sys.argv[2:]))
for key in ("gpu_used_pct", "memory_used_pct", "memory_total_mib", "memory_used_mib", "power_w", "clocks_sm_mhz"):
    value = rec.get(key, "")
    if value in ("", "N/A", "[N/A]", "Not Supported"):
        rec[key] = None
        continue
    try:
        rec[key] = float(value) if "." in value else int(value)
    except ValueError:
        pass
with open(path, "a", encoding="utf-8") as f:
    f.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
PY
}

snapshot_once()
{
	echo "== spark gpu status =="
	date -u +"utc=%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date || true
	echo "columns: node,target,host,gpu,gpu_name,gpu_used_pct,memory_used_pct,memory_used_mib,memory_total_mib,power_w,clocks_sm_mhz,pstate"
	i=0
	for target in "$@"; do
		node="spark$i"
		out="$(ssh_run "$target" '
set -eu
echo "host=$(hostname 2>/dev/null || echo unknown)"
date -u +"utc=%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date || true
if command -v nvidia-smi >/dev/null 2>&1; then
	nvidia-smi --query-gpu=index,name,utilization.gpu,utilization.memory,memory.total,memory.used,power.draw,clocks.sm,pstate --format=csv,noheader,nounits 2>/dev/null || echo "nvidia_smi_query_failed"
else
	echo "nvidia_smi_missing"
fi
' 2>&1)" || {
			echo "$node,$target,unreachable,,,,,,,,,"
			i=$((i + 1))
			continue
		}
		host="$(printf '%s\n' "$out" | sed -n 's/^host=//p' | head -n 1)"
		utc="$(printf '%s\n' "$out" | sed -n 's/^utc=//p' | head -n 1)"
		rows="$(printf '%s\n' "$out" | sed '/^host=/d;/^utc=/d;/^$/d')"
		if printf '%s\n' "$rows" | grep -Eq 'nvidia_smi_(missing|query_failed)'; then
			echo "$node,$target,${host:-unknown},nvidia-smi-unavailable,,,,,,,,"
			i=$((i + 1))
			continue
		fi
		printf '%s\n' "$rows" | while IFS=, read -r gpu name gpu_pct mem_pct mem_total mem_used power_w clock_sm pstate rest; do
			gpu="$(printf '%s' "$gpu" | sed 's/^ *//;s/ *$//')"
			name="$(printf '%s' "$name" | sed 's/^ *//;s/ *$//')"
			gpu_pct="$(printf '%s' "$gpu_pct" | sed 's/^ *//;s/ *$//')"
			mem_pct="$(printf '%s' "$mem_pct" | sed 's/^ *//;s/ *$//')"
			mem_total="$(printf '%s' "$mem_total" | sed 's/^ *//;s/ *$//')"
			mem_used="$(printf '%s' "$mem_used" | sed 's/^ *//;s/ *$//')"
			power_w="$(printf '%s' "$power_w" | sed 's/^ *//;s/ *$//')"
			clock_sm="$(printf '%s' "$clock_sm" | sed 's/^ *//;s/ *$//')"
			pstate="$(printf '%s' "$pstate" | sed 's/^ *//;s/ *$//')"
			echo "$node,$target,${host:-unknown},$gpu,$name,$gpu_pct,$mem_pct,$mem_used,$mem_total,$power_w,$clock_sm,$pstate"
			emit_jsonl "$target" "$node" "${host:-unknown}" "${utc:-}" "$gpu" "$name" "$gpu_pct" "$mem_pct" "$mem_total" "$mem_used" "$power_w" "$clock_sm" "$pstate"
		done
		i=$((i + 1))
	done
}

iter=0
while :; do
	snapshot_once "$@"
	iter=$((iter + 1))
	if [ "$watch" -eq 0 ] && [ "$iter" -ge "$count" ]; then
		break
	fi
	if [ "$count" -ne 0 ] && [ "$iter" -ge "$count" ]; then
		break
	fi
	sleep "$interval"
done
