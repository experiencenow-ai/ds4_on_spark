#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Simulate an ordered Spark ring on one machine using Centaur v73.

This is a filesystem-only rehearsal: every "Spark" is a separate Centaur root
directory under one workdir, so `hyor-ring-step` can copy manifests/objects
bidirectionally (it requires writable peer roots).

Environment:
  CENTAUR_ROOT      Extracted Centaur dir containing centaur.py (required)
  CENTAUR_VENV      Centaur venv dir containing bin/python3 (required)
  SPARK_NODE_COUNT  Number of Spark nodes to simulate (default: 3)
  RING_WORKDIR      Base workdir (default: ~/centaur-smoke/v73/ring_sim)
  RING_RUN_ID       Optional run id (writes under RING_WORKDIR/run/<run_id>)
  RING_LOG          Optional log path (duplicates stdout/stderr via tee)
  NODE_TYPE         Node type label (default: default)
  RING_TRACE        Set to 1 to enable shell tracing

Example:
  export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
  export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
  SPARK_NODE_COUNT=3 sh ./scripts/centaur_spark_ring_sim_v73.sh
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

centaur_root="${CENTAUR_ROOT:-}"
venv_dir="${CENTAUR_VENV:-}"
if [ "$centaur_root" = "" ] || [ "$venv_dir" = "" ]; then
	echo "CENTAUR_ROOT and CENTAUR_VENV are required" >&2
	usage >&2
	exit 2
fi
if [ ! -f "$centaur_root/centaur.py" ]; then
	echo "missing centaur.py under CENTAUR_ROOT: $centaur_root" >&2
	exit 2
fi
py="$venv_dir/bin/python3"
if [ ! -x "$py" ]; then
	echo "missing venv python3 under CENTAUR_VENV: $venv_dir" >&2
	exit 2
fi

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

node_count="${SPARK_NODE_COUNT:-3}"
case "$node_count" in
	*[!0-9]*|"")
		echo "SPARK_NODE_COUNT must be an integer >= 2" >&2
		exit 2
		;;
esac
if [ "$node_count" -lt 2 ]; then
	echo "SPARK_NODE_COUNT must be >= 2" >&2
	exit 2
fi

base_workdir="${RING_WORKDIR:-$HOME/centaur-smoke/v73/ring_sim}"
run_id="${RING_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	workdir="$base_workdir"
else
	workdir="$base_workdir/run/$run_id"
fi
node_type="${NODE_TYPE:-default}"
ctrl="$workdir/controller"

if [ "${RING_TRACE:-0}" = "1" ]; then
	set -x
fi

log="${RING_LOG:-}"
if [ "$log" != "" ]; then
	need_cmd tee
	need_cmd mkfifo
	need_cmd dirname
	mkdir -p "$(dirname -- "$log")"
	fifo="$workdir/.centaur_ring_sim_log.fifo"
	rm -f "$fifo"
	mkdir -p "$workdir"
	mkfifo "$fifo"
	exec 3>&1 4>&2
	tee "$log" <"$fifo" &
	teepid="$!"
	cleanup_log()
	{
		exec >&3 2>&4
		rm -f "$fifo"
		wait "$teepid" 2>/dev/null || true
	}
	trap 'cleanup_log' EXIT INT TERM
	exec >"$fifo" 2>&1
fi

value_at()
{
	prefix="$1"
	idx="$2"
	eval "printf '%s' \"\${${prefix}_${idx}:-}\""
}

centaur()
{
	"$py" -u "$centaur_root/centaur.py" "$@"
}

left_index()
{
	idx="$1"
	echo $(((idx + node_count - 1) % node_count))
}

right_index()
{
	idx="$1"
	echo $(((idx + 1) % node_count))
}

i=0
while [ "$i" -lt "$node_count" ]; do
	eval "s$i=\$workdir/spark$i"
	i=$((i + 1))
done

mkdir -p "$ctrl" "$workdir/publish/baseline" "$workdir/publish/node_type_default"
i=0
while [ "$i" -lt "$node_count" ]; do
	mkdir -p "$(value_at s "$i")"
	i=$((i + 1))
done

echo "== ring sim workdir =="
echo "$workdir"
echo "node_count=$node_count"

echo "== centaur package facts =="
"$py" -V
decomposer_version="$("$py" -c 'import ast,sys
p=sys.argv[1]
try:
    t=open(p,"r",encoding="utf-8",errors="replace").read()
except Exception:
    print("")
    raise SystemExit(0)
try:
    m=ast.parse(t)
except Exception:
    print("")
    raise SystemExit(0)
v=""
for node in getattr(m,"body",[]):
    if isinstance(node, ast.Assign):
        for tgt in getattr(node,"targets",[]):
            if isinstance(tgt, ast.Name) and tgt.id=="DECOMPOSER_VERSION":
                val=getattr(node,"value",None)
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    v=val.value
print(v)' "$centaur_root/centaur.py")"
if [ "$decomposer_version" = "" ]; then
	decomposer_version="(unknown)"
fi
echo "decomposer_version: $decomposer_version"

echo "== pip freeze (sanitized) =="
"$py" -m pip freeze | sed -E 's@file://[^ ]+@file://REDACTED@g'

echo "== init roots =="
left="$(value_at s "$(left_index 0)")"
right="$(value_at s "$(right_index 0)")"
set -- hyor-sync-init "$ctrl" --node-id spark0 --node-type "$node_type" --left-peer-root "$left" --right-peer-root "$right"
i=1
while [ "$i" -lt "$node_count" ]; do
	set -- "$@" --broadcast-peer-root "$(value_at s "$i")"
	i=$((i + 1))
done
centaur "$@"

i=0
while [ "$i" -lt "$node_count" ]; do
	root_i="$(value_at s "$i")"
	left="$(value_at s "$(left_index "$i")")"
	right="$(value_at s "$(right_index "$i")")"
	centaur hyor-sync-init "$root_i" --node-id "spark$i" --node-type "$node_type" --left-peer-root "$left" --right-peer-root "$right"
	i=$((i + 1))
done

echo "== publish baseline + node_type from controller =="
printf "baseline\n" >"$workdir/publish/baseline/baseline.txt"
printf "node-type\n" >"$workdir/publish/node_type_default/model.txt"
centaur hyor-sync-publish "$ctrl" baseline "$workdir/publish/baseline" --label ring-sim-v73
centaur hyor-sync-publish "$ctrl" node_type "$workdir/publish/node_type_default" --selector "$node_type" --label ring-sim-v73

echo "== ring step (metadata) =="
centaur hyor-ring-step "$ctrl" --scope metadata
i=0
while [ "$i" -lt "$node_count" ]; do
	centaur hyor-ring-step "$(value_at s "$i")" --scope metadata
	i=$((i + 1))
done

echo "== ring step (effective) =="
centaur hyor-ring-step "$ctrl" --scope effective
i=0
while [ "$i" -lt "$node_count" ]; do
	centaur hyor-ring-step "$(value_at s "$i")" --scope effective
	i=$((i + 1))
done

echo "== effective manifests (non-controller nodes) =="
mkdir -p "$workdir/effective_manifests"
i=1
while [ "$i" -lt "$node_count" ]; do
	centaur hyor-sync-effective "$(value_at s "$i")" "spark$i" --node-type "$node_type" --output "$workdir/effective_manifests/hyor_effective_manifest_spark$i.json"
	i=$((i + 1))
done

echo "== effective apply (non-controller nodes) =="
i=1
while [ "$i" -lt "$node_count" ]; do
	mkdir -p "$workdir/effective/spark$i"
	centaur hyor-sync-apply "$(value_at s "$i")" "spark$i" --node-type "$node_type" --output-dir "$workdir/effective/spark$i" --clean
	i=$((i + 1))
done

echo "== done =="
echo "workdir: $workdir"
