#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Simulate a 3-node Spark ring (Spark0/1/2) on one machine using Centaur v73.

This is a filesystem-only rehearsal: every "Spark" is just a separate Centaur root
directory under one workdir, so `hyor-ring-step` can copy manifests/objects
bidirectionally (it requires writable peer roots).

Environment:
  CENTAUR_ROOT     Extracted Centaur dir containing centaur.py (required)
  CENTAUR_VENV     Centaur venv dir containing bin/python3 (required)
  RING_WORKDIR     Base workdir (default: ~/centaur-smoke/v73/ring_sim_spark12)
  NODE_TYPE        Node type label (default: default)
  RING_TRACE       Set to 1 to enable shell tracing (prints exact commands)

Example:
  export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
  export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
  sh ./scripts/centaur_spark_ring_sim_spark12_v73.sh
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

workdir="${RING_WORKDIR:-$HOME/centaur-smoke/v73/ring_sim_spark12}"
node_type="${NODE_TYPE:-default}"

if [ "${RING_TRACE:-0}" = "1" ]; then
	set -x
fi

ctrl="$workdir/controller"
s0="$workdir/spark0"
s1="$workdir/spark1"
s2="$workdir/spark2"

mkdir -p "$ctrl" "$s0" "$s1" "$s2" "$workdir/publish/baseline" "$workdir/publish/node_type_default"

centaur()
{
	"$py" -u "$centaur_root/centaur.py" "$@"
}

echo "== ring sim (spark12) workdir =="
echo "$workdir"

echo "== init roots =="
centaur hyor-sync-init "$ctrl" --node-id spark0 --node-type "$node_type" --left-peer-root "$s2" --right-peer-root "$s1" --broadcast-peer-root "$s1" --broadcast-peer-root "$s2"
centaur hyor-sync-init "$s0" --node-id spark0 --node-type "$node_type" --left-peer-root "$s2" --right-peer-root "$s1"
centaur hyor-sync-init "$s1" --node-id spark1 --node-type "$node_type" --left-peer-root "$s0" --right-peer-root "$s2"
centaur hyor-sync-init "$s2" --node-id spark2 --node-type "$node_type" --left-peer-root "$s1" --right-peer-root "$s0"

echo "== publish baseline + node_type from controller =="
printf "baseline\n" >"$workdir/publish/baseline/baseline.txt"
printf "node-type\n" >"$workdir/publish/node_type_default/model.txt"
centaur hyor-sync-publish "$ctrl" baseline "$workdir/publish/baseline" --label ring-sim-spark12-v73
centaur hyor-sync-publish "$ctrl" node_type "$workdir/publish/node_type_default" --selector "$node_type" --label ring-sim-spark12-v73

echo "== ring step (metadata) =="
centaur hyor-ring-step "$ctrl" --scope metadata
centaur hyor-ring-step "$s0" --scope metadata
centaur hyor-ring-step "$s1" --scope metadata
centaur hyor-ring-step "$s2" --scope metadata

echo "== ring step (effective) =="
centaur hyor-ring-step "$ctrl" --scope effective
centaur hyor-ring-step "$s0" --scope effective
centaur hyor-ring-step "$s1" --scope effective
centaur hyor-ring-step "$s2" --scope effective

echo "== effective manifests (spark1/2) =="
mkdir -p "$workdir/effective_manifests"
centaur hyor-sync-effective "$s1" spark1 --node-type "$node_type" --output "$workdir/effective_manifests/hyor_effective_manifest_spark1.json"
centaur hyor-sync-effective "$s2" spark2 --node-type "$node_type" --output "$workdir/effective_manifests/hyor_effective_manifest_spark2.json"

echo "== effective apply (spark1/2) =="
mkdir -p "$workdir/effective/spark1" "$workdir/effective/spark2"
centaur hyor-sync-apply "$s1" spark1 --node-type "$node_type" --output-dir "$workdir/effective/spark1" --clean
centaur hyor-sync-apply "$s2" spark2 --node-type "$node_type" --output-dir "$workdir/effective/spark2" --clean

echo "== done =="
echo "workdir: $workdir"
