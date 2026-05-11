#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Centaur v73 ring-step coordinator for Spark1/Spark2 using rsync staging.

This runs on Spark0 (or any orchestrator host that can SSH to Spark1/2) and
works around the Centaur constraint that `hyor-ring-step` requires local,
writable peer roots. It does this by:

  1) Maintaining local working copies of node roots for spark0..spark2
  2) Running ring-step locally across those roots
  3) rsync'ing the mutated node roots back to Spark1/2

Inputs:
  - You must already have Centaur extracted + venv on the orchestrator host.
    The Spark0 v73 smoke (`scripts/centaur_spark0_v73_smoke.sh`) creates:
      ~/centaur-smoke/v73/run/centaur_spec_impl_v73
      ~/centaur-smoke/v73/run/venv

Usage:
  centaur_spark_ring_rsync_spark12_v73.sh <spark1_user@host> <spark2_user@host> [remote_base_dir]

Environment:
  CENTAUR_ROOT     Extracted Centaur dir containing centaur.py
                  (default: ~/centaur-smoke/v73/run/centaur_spec_impl_v73)
  CENTAUR_VENV     Centaur venv dir containing bin/python3
                  (default: ~/centaur-smoke/v73/run/venv)
  RING_WORKDIR     Local orchestrator workdir (default: ~/centaur-smoke/v73/ring_rsync_spark12)
  NODE_TYPE        Node type label (default: default)
  RING_APPLY       If set to 1, also run `hyor-sync-apply` locally for Spark1/2
                  and rsync the materialized `effective_spark{1,2}` dirs back.
  RING_TRACE       Set to 1 to enable shell tracing (prints exact commands)
  SSH_OPTS         Optional ssh options override (default includes BatchMode + temp known_hosts)

Notes:
  - No sudo/service changes.
  - remote_base_dir should be a dedicated Centaur ring directory (safe to rsync --delete).
USAGE
}

case "${1:-}" in
	-h|--help|"")
	usage
	exit 2
	;;
esac

if [ "${2:-}" = "" ]; then
	usage >&2
	exit 2
fi

spark1="$1"
spark2="$2"
remote_base="${3:-}"
if [ "$remote_base" = "" ]; then
	remote_base="~/centaur-smoke/v73/ring_node"
fi

centaur_root="${CENTAUR_ROOT:-$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}"
venv_dir="${CENTAUR_VENV:-$HOME/centaur-smoke/v73/run/venv}"
workdir="${RING_WORKDIR:-$HOME/centaur-smoke/v73/ring_rsync_spark12}"
node_type="${NODE_TYPE:-default}"

if [ "${RING_TRACE:-0}" = "1" ]; then
	set -x
fi

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd ssh
need_cmd rsync

if [ ! -f "$centaur_root/centaur.py" ]; then
	echo "missing centaur.py under CENTAUR_ROOT: $centaur_root" >&2
	exit 2
fi
py="$venv_dir/bin/python3"
if [ ! -x "$py" ]; then
	echo "missing venv python3 under CENTAUR_VENV: $venv_dir" >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

rsync_pull()
{
	target="$1"
	remote_path="$2"
	local_path="$3"
	mkdir -p "$local_path"
	rsync -av -e "ssh $SSH_OPTS" --delete "$target:$remote_path/" "$local_path/"
}

rsync_push()
{
	local_path="$1"
	target="$2"
	remote_path="$3"
	ssh_run "$target" "mkdir -p $remote_path"
	rsync -av -e "ssh $SSH_OPTS" --delete "$local_path/" "$target:$remote_path/"
}

centaur()
{
	"$py" -u "$centaur_root/centaur.py" "$@"
}

ctrl="$workdir/controller"
s0="$workdir/spark0"
s1="$workdir/spark1"
s2="$workdir/spark2"

remote_s1="$remote_base/hyor/node_spark1"
remote_s2="$remote_base/hyor/node_spark2"

echo "== centaur v73 ring rsync step (spark12) =="
echo "workdir: $workdir"
echo "centaur_root: $centaur_root"
echo "venv_dir: $venv_dir"
echo "node_type: $node_type"
echo "remote_base: $remote_base"
echo "spark1: $spark1"
echo "spark2: $spark2"

echo "== ensure remote dirs =="
ssh_run "$spark1" "mkdir -p $remote_s1"
ssh_run "$spark2" "mkdir -p $remote_s2"

echo "== pull remote node roots (seed) =="
rsync_pull "$spark1" "$remote_s1" "$s1"
rsync_pull "$spark2" "$remote_s2" "$s2"

mkdir -p "$ctrl" "$s0" "$workdir/publish/baseline" "$workdir/publish/node_type_default"

echo "== init roots (local working copies) =="
centaur hyor-sync-init "$ctrl" --node-id spark0 --node-type "$node_type" --left-peer-root "$s2" --right-peer-root "$s1" --broadcast-peer-root "$s1" --broadcast-peer-root "$s2"
centaur hyor-sync-init "$s0" --node-id spark0 --node-type "$node_type" --left-peer-root "$s2" --right-peer-root "$s1"
centaur hyor-sync-init "$s1" --node-id spark1 --node-type "$node_type" --left-peer-root "$s0" --right-peer-root "$s2"
centaur hyor-sync-init "$s2" --node-id spark2 --node-type "$node_type" --left-peer-root "$s1" --right-peer-root "$s0"

echo "== publish baseline + node_type from controller =="
printf "baseline\n" >"$workdir/publish/baseline/baseline.txt"
printf "node-type\n" >"$workdir/publish/node_type_default/model.txt"
centaur hyor-sync-publish "$ctrl" baseline "$workdir/publish/baseline" --label ring-rsync-spark12-v73
centaur hyor-sync-publish "$ctrl" node_type "$workdir/publish/node_type_default" --selector "$node_type" --label ring-rsync-spark12-v73

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

echo "== effective manifests (local) =="
mkdir -p "$workdir/effective_manifests"
centaur hyor-sync-effective "$s1" spark1 --node-type "$node_type" --output "$workdir/effective_manifests/hyor_effective_manifest_spark1.json"
centaur hyor-sync-effective "$s2" spark2 --node-type "$node_type" --output "$workdir/effective_manifests/hyor_effective_manifest_spark2.json"

echo "== push mutated node roots back to Spark1/2 =="
rsync_push "$s1" "$spark1" "$remote_s1"
rsync_push "$s2" "$spark2" "$remote_s2"

if [ "${RING_APPLY:-}" = "1" ]; then
	echo "== optional: effective apply + push (RING_APPLY=1) =="
	mkdir -p "$workdir/effective/spark1" "$workdir/effective/spark2"
	centaur hyor-sync-apply "$s1" spark1 --node-type "$node_type" --output-dir "$workdir/effective/spark1" --clean
	centaur hyor-sync-apply "$s2" spark2 --node-type "$node_type" --output-dir "$workdir/effective/spark2" --clean
	rsync_push "$workdir/effective/spark1" "$spark1" "$remote_base/effective_spark1"
	rsync_push "$workdir/effective/spark2" "$spark2" "$remote_base/effective_spark2"
fi

echo "== done =="
echo "workdir: $workdir"
