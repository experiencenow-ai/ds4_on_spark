#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_rsync_fetch_artifacts.sh <spark0_user@host> <ring_run_id> [remote_ring_workdir] [local_out_dir]

Fetches a small artifact bundle from a Spark1/Spark2 rsync-staged ring run that
was executed on Spark0.

Defaults:
  remote_ring_workdir: ~/centaur-smoke/v73/ring_rsync_spark12
  local_out_dir:       /private/tmp/centaur-ring/spark12-v73/<ring_run_id> (or /tmp/... if /private/tmp is unavailable)

Environment:
  SSH_OPTS   Optional ssh options override (default includes BatchMode + temp known_hosts)

Bundle contents (when present):
  - ring_rsync.log
  - effective_manifests/

Notes:
  - Does not fetch venvs, Centaur sources, or full node roots.
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

target="$1"
run_id="$2"
remote_workdir="${3:-}"
local_out="${4:-}"

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
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

if [ "$remote_workdir" = "" ]; then
	remote_workdir="~/centaur-smoke/v73/ring_rsync_spark12"
fi

if [ "$local_out" = "" ]; then
	base="/tmp/centaur-ring/spark12-v73"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp/centaur-ring/spark12-v73"
	fi
	local_out="$base/$run_id"
fi

remote_run="$remote_workdir/run/$run_id"

echo "== fetch centaur ring artifacts (spark12 v73) =="
echo "target: $target"
echo "remote_run: $remote_run"
echo "local_out: $local_out"

mkdir -p "$local_out"

if ssh $SSH_OPTS "$target" "test -f $remote_run/ring_rsync.log"; then
	rsync -av -e "ssh $SSH_OPTS" "$target:$remote_run/ring_rsync.log" "$local_out/"
else
	echo "missing remote log: $remote_run/ring_rsync.log" >&2
fi

if ssh $SSH_OPTS "$target" "test -d $remote_run/effective_manifests"; then
	rsync -av -e "ssh $SSH_OPTS" "$target:$remote_run/effective_manifests/" "$local_out/effective_manifests/"
else
	echo "missing remote effective_manifests/: $remote_run/effective_manifests" >&2
fi

echo "== done =="
ls -la "$local_out" | sed -n '1,40p'