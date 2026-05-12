#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_rsync_run.sh <spark0_user@host> <spark1_user@host> <spark2_user@host> [remote_base_dir] [local_log]

Runs the Spark1/Spark2 rsync-staged ring-step on Spark0, passing Spark1/2 as SSH targets. No sudo/service changes; no secrets.

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
  RING_SKIP_PREFLIGHT Set to 1 to skip SSH preflight checks

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
ring="$root/scripts/centaur_spark_ring_rsync_v73.sh"
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

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

copy_to_remote()
{
	src="$1"
	dst="$2"
	if command -v rsync >/dev/null 2>&1; then
		rsync -av -e "ssh $SSH_OPTS" "$src" "$dst"
		return 0
	fi
	if command -v scp >/dev/null 2>&1; then
		scp $SSH_OPTS "$src" "$dst"
		return 0
	fi
	return 1
}

ssh_preflight()
{
	t="$1"
	if ssh $SSH_OPTS "$t" "true" >/dev/null 2>&1; then
		echo "preflight: ssh ok: $t"
		return 0
	fi
	echo "preflight: ssh failed: $t" >&2
	echo "hint: check DNS/SSH reachability and keys; try:" >&2
	echo "  REDACT=1 ./scripts/mac_spark_discovery.sh $(printf "%s" "$t" | sed 's/^[^@]*@//')" >&2
	return 1
}

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

if [ "${RING_SKIP_PREFLIGHT:-0}" != "1" ]; then
	echo "== preflight ssh =="
	ssh_preflight "$spark0" || exit 21
	ssh_preflight "$spark1" || exit 22
	ssh_preflight "$spark2" || exit 23
else
	echo "== skip preflight (RING_SKIP_PREFLIGHT=1) =="
fi

if [ "${RING_SKIP_STAGE:-0}" != "1" ]; then
	echo "== stage v73 zip to spark1/2 =="
	"$stage12" "$spark1" "$spark2" "~/centaur-smoke/v73"
else
	echo "== skip stage (RING_SKIP_STAGE=1) =="
fi

ring_workdir_abs="$(ssh $SSH_OPTS "$spark0" "mkdir -p $ring_workdir && cd $ring_workdir && pwd -P")"
remote_log_abs="${remote_log}"
if [ "${RING_LOG:-}" = "" ]; then
	remote_log_abs="$ring_workdir_abs/run/$run_id/ring_rsync.log"
else
	remote_log_abs="$(ssh $SSH_OPTS "$spark0" "python3 -c 'import os,sys; print(os.path.abspath(os.path.expandvars(os.path.expanduser(sys.argv[1]))))' \"$remote_log_abs\"")"
fi
remote_ring_script="$ring_workdir_abs/centaur_spark_ring_rsync_v73.sh"

ssh_cmd="export CENTAUR_ROOT=\"${CENTAUR_ROOT:-\$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}\" && export CENTAUR_VENV=\"${CENTAUR_VENV:-\$HOME/centaur-smoke/v73/run/venv}\" && export RING_WORKDIR=\"$ring_workdir_abs\" && export RING_RUN_ID=\"$run_id\" && export RING_LOG=\"$remote_log_abs\""
if [ "${NODE_TYPE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export NODE_TYPE=\"${NODE_TYPE}\""
fi
if [ "${RING_APPLY:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export RING_APPLY=\"${RING_APPLY}\""
fi
if [ "${RING_TRACE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export RING_TRACE=\"${RING_TRACE}\""
fi

remote_cmd="$ssh_cmd && mkdir -p \"$(dirname -- "$remote_log_abs")\" && sh \"$remote_ring_script\" --remote-base \"$remote_base\" \"$spark1\" \"$spark2\""

if copy_to_remote "$ring" "$spark0:$remote_ring_script"; then
	echo "== stage ring script to spark0 =="
	ssh $SSH_OPTS "$spark0" "chmod 0755 \"$remote_ring_script\""
	echo "== run ring rsync (remote) =="
	echo "ssh $SSH_OPTS $spark0 \"$remote_cmd\""
	if [ "$local_log" = "" ]; then
		ssh $SSH_OPTS "$spark0" "$remote_cmd"
	else
		need_cmd tee
		need_cmd dirname
		mkdir -p "$(dirname -- "$local_log")"
		ssh $SSH_OPTS "$spark0" "$remote_cmd" 2>&1 | tee "$local_log"
	fi
else
	echo "== run ring rsync (streamed; no rsync/scp on Mac) =="
	stream_cmd="$ssh_cmd && mkdir -p \"$(dirname -- "$remote_log_abs")\" && sh -s -- --remote-base \"$remote_base\" \"$spark1\" \"$spark2\""
	echo "ssh $SSH_OPTS $spark0 \"$stream_cmd\" < $ring"
	if [ "$local_log" = "" ]; then
		ssh $SSH_OPTS "$spark0" "$stream_cmd" < "$ring"
	else
		need_cmd tee
		need_cmd dirname
		mkdir -p "$(dirname -- "$local_log")"
		ssh $SSH_OPTS "$spark0" "$stream_cmd" < "$ring" 2>&1 | tee "$local_log"
	fi
fi
