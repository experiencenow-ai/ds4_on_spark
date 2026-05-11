#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_rsync_run.sh <spark0_user@host> <spark1_user@host> <spark2_user@host> [remote_base_dir] [local_log]

Runs the Spark1/Spark2 rsync-staged ring-step by streaming
`scripts/centaur_spark_ring_rsync_spark12_v73.sh` to Spark0, passing Spark1/2
as SSH targets. No sudo/service changes; no secrets.

Prereq:
  - Run the Spark0 v73 smoke first so Spark0 has:
      ~/centaur-smoke/v73/run/centaur_spec_impl_v73/centaur.py
      ~/centaur-smoke/v73/run/venv/bin/python3

Environment:
  SSH_OPTS         Optional ssh options override (default includes BatchMode + temp known_hosts)
  CENTAUR_ROOT     Spark0 path to extracted Centaur root (default: ~/centaur-smoke/v73/run/centaur_spec_impl_v73)
  CENTAUR_VENV     Spark0 path to Centaur venv dir (default: ~/centaur-smoke/v73/run/venv)
  RING_WORKDIR     Spark0 ring workdir (default: ~/centaur-smoke/v73/ring_rsync_spark12)
  RING_RUN_ID      Optional run id (default: generated UTC timestamp)
  RING_LOG         Optional Spark0 log path (default: $RING_WORKDIR/run/$RING_RUN_ID/ring_rsync.log)
  NODE_TYPE        Optional node type label (default: default)
  RING_APPLY       Set to 1 to materialize+push effective dirs to Spark1/2
  RING_TRACE       Set to 1 to enable remote shell tracing (prints exact commands)
  RING_SKIP_STAGE  Set to 1 to skip staging the v73 zip to Spark1/2

Notes:
  - remote_base_dir is a directory on Spark1/2 used for ring node roots.
    Default: ~/centaur-smoke/v73/ring_node (safe to rsync --delete).
  - If local_log is provided, stdout/stderr are tee'd locally (Mac-side).
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

if [ "${2:-}" = "" ] || [ "${3:-}" = "" ]; then
	usage >&2
	exit 2
fi

spark0="$1"
spark1="$2"
spark2="$3"
remote_base="${4:-}"
local_log="${5:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ring="$root/scripts/centaur_spark_ring_rsync_spark12_v73.sh"
stage12="$root/scripts/centaur_spark12_v73_stage.sh"

if [ ! -f "$ring" ]; then
	echo "missing ring script: $ring" >&2
	exit 2
fi
if [ ! -x "$stage12" ]; then
	echo "missing stage script: $stage12" >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

if [ "$remote_base" = "" ]; then
	remote_base="~/centaur-smoke/v73/ring_node"
fi

run_id="${RING_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

ring_workdir="${RING_WORKDIR:-}"
remote_log="${RING_LOG:-}"
if [ "$ring_workdir" = "" ]; then
	ring_workdir="\$HOME/centaur-smoke/v73/ring_rsync_spark12"
fi
if [ "$remote_log" = "" ]; then
	remote_log="$ring_workdir/run/$run_id/ring_rsync.log"
fi

echo "== centaur v73 ring rsync run (spark12) =="
echo "spark0: $spark0"
echo "spark1: $spark1"
echo "spark2: $spark2"
echo "remote_base: $remote_base"
echo "ring_run_id: $run_id"
echo "spark0_ring_workdir: $ring_workdir"
echo "spark0_ring_log: $remote_log"
if [ "$local_log" != "" ]; then
	echo "local_log: $local_log"
fi

if [ "${RING_SKIP_STAGE:-0}" != "1" ]; then
	echo "== stage v73 zip to spark1/2 =="
	"$stage12" "$spark1" "$spark2" "~/centaur-smoke/v73"
else
	echo "== skip stage (RING_SKIP_STAGE=1) =="
fi

ssh_cmd="export CENTAUR_ROOT=\"${CENTAUR_ROOT:-\\$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}\" && export CENTAUR_VENV=\"${CENTAUR_VENV:-\\$HOME/centaur-smoke/v73/run/venv}\" && export RING_WORKDIR=\"$ring_workdir\" && export RING_RUN_ID=\"$run_id\" && export RING_LOG=\"$remote_log\""
if [ "${NODE_TYPE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export NODE_TYPE=\"${NODE_TYPE}\""
fi
if [ "${RING_APPLY:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export RING_APPLY=\"${RING_APPLY}\""
fi
if [ "${RING_TRACE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export RING_TRACE=\"${RING_TRACE}\""
fi
ssh_cmd="$ssh_cmd && mkdir -p \"$(dirname -- "$remote_log")\" && sh -s -- \"$spark1\" \"$spark2\" \"$remote_base\""

echo "== run ring rsync (streamed) =="
echo "ssh $SSH_OPTS $spark0 \"$ssh_cmd\" < $ring"

if [ "$local_log" = "" ]; then
	ssh $SSH_OPTS "$spark0" "$ssh_cmd" < "$ring"
else
	ssh $SSH_OPTS "$spark0" "$ssh_cmd" < "$ring" 2>&1 | tee "$local_log"
fi