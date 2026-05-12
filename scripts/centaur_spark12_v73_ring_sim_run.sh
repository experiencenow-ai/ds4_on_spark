#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_sim_run.sh <spark0_user@host> [remote_ring_workdir] [local_log]

Runs a Spark0-local Spark1/Spark2 ring simulation by streaming
`scripts/centaur_spark_ring_sim_spark12_v73.sh` to Spark0.

This is the recommended rehearsal before Spark1/2 hardware exists. It requires:
  - Spark0 has already run the v73 smoke (Centaur extracted + venv present).

Environment:
  SSH_OPTS         Optional ssh options override (default includes BatchMode + temp known_hosts)
  CENTAUR_ROOT     Spark0 path to extracted Centaur root (default: ~/centaur-smoke/v73/run/centaur_spec_impl_v73)
  CENTAUR_VENV     Spark0 path to Centaur venv dir (default: ~/centaur-smoke/v73/run/venv)
  RING_WORKDIR     Spark0 ring sim base workdir (default: ~/centaur-smoke/v73/ring_sim_spark12)
  RING_RUN_ID      Optional run id (default: generated UTC timestamp)
  RING_LOG         Optional Spark0 log path (default: $RING_WORKDIR/run/$RING_RUN_ID/ring_sim.log)
  NODE_TYPE        Optional node type label (default: default)
  RING_TRACE       Set to 1 to enable remote shell tracing (prints exact commands)
  RING_SKIP_PREFLIGHT Set to 1 to skip SSH + smoke-footprint preflight checks

Notes:
  - If local_log is provided, stdout/stderr are tee'd locally (Mac-side).
  - Fetch a small sanitized bundle back to your Mac with:
      sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh <spark0_user@host> "$RING_RUN_ID"
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

target="$1"
remote_workdir="${2:-}"
local_log="${3:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ring="$root/scripts/centaur_spark_ring_sim_spark12_v73.sh"

if [ ! -f "$ring" ]; then
	echo "missing ring sim script: $ring" >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

ssh_preflight()
{
	if ssh $SSH_OPTS "$target" "true" >/dev/null 2>&1; then
		echo "preflight: ssh ok: $target"
		return 0
	fi
	echo "preflight: ssh failed: $target" >&2
	echo "hint: check DNS/SSH reachability and keys; try:" >&2
	echo "  REDACT=1 ./scripts/mac_spark_discovery.sh $(printf "%s" "$target" | sed 's/^[^@]*@//')" >&2
	return 1
}

smoke_footprint_preflight()
{
	remote_root="${CENTAUR_ROOT:-\\$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}"
	remote_venv="${CENTAUR_VENV:-\\$HOME/centaur-smoke/v73/run/venv}"
	if ssh $SSH_OPTS "$target" "test -f \"$remote_root/centaur.py\" && test -x \"$remote_venv/bin/python3\""; then
		echo "preflight: smoke footprint ok: CENTAUR_ROOT=$remote_root CENTAUR_VENV=$remote_venv"
		return 0
	fi
	echo "preflight: missing Centaur smoke footprint on Spark0" >&2
	echo "expected on Spark0:" >&2
	echo "  $remote_root/centaur.py" >&2
	echo "  $remote_venv/bin/python3" >&2
	echo "run first (from your Mac):" >&2
	echo "  sh ./scripts/centaur_spark0_v73_run.sh $target" >&2
	return 1
}

if [ "${RING_SKIP_PREFLIGHT:-0}" != "1" ]; then
	echo "== preflight ssh =="
	ssh_preflight || exit 21
	echo "== preflight smoke footprint =="
	smoke_footprint_preflight || exit 22
else
	echo "== skip preflight (RING_SKIP_PREFLIGHT=1) =="
fi

run_id="${RING_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

ring_workdir="${RING_WORKDIR:-}"
remote_log="${RING_LOG:-}"
if [ "$remote_workdir" != "" ]; then
	ring_workdir="$remote_workdir"
fi
if [ "$ring_workdir" = "" ]; then
	ring_workdir="\\$HOME/centaur-smoke/v73/ring_sim_spark12"
fi
if [ "$remote_log" = "" ]; then
	remote_log="$ring_workdir/run/$run_id/ring_sim.log"
fi

echo "== centaur v73 ring sim run (spark12) =="
echo "spark0: $target"
echo "ring_run_id: $run_id"
echo "spark0_ring_workdir: $ring_workdir"
echo "spark0_ring_log: $remote_log"
if [ "$local_log" != "" ]; then
	echo "local_log: $local_log"
fi

ssh_cmd="export CENTAUR_ROOT=\"${CENTAUR_ROOT:-\\$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}\" && export CENTAUR_VENV=\"${CENTAUR_VENV:-\\$HOME/centaur-smoke/v73/run/venv}\" && export RING_WORKDIR=\"$ring_workdir\" && export RING_RUN_ID=\"$run_id\" && export RING_LOG=\"$remote_log\""
if [ "${NODE_TYPE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export NODE_TYPE=\"${NODE_TYPE}\""
fi
if [ "${RING_TRACE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export RING_TRACE=\"${RING_TRACE}\""
fi
ssh_cmd="$ssh_cmd && mkdir -p \"$(dirname -- "$remote_log")\" && sh -s"

echo "== run ring sim (streamed) =="
echo "ssh $SSH_OPTS $target \"$ssh_cmd\" < $ring"

if [ "$local_log" = "" ]; then
	ssh $SSH_OPTS "$target" "$ssh_cmd" < "$ring"
else
	ssh $SSH_OPTS "$target" "$ssh_cmd" < "$ring" 2>&1 | tee "$local_log"
fi

echo "== next: fetch artifacts (Mac) =="
echo "sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh $target \"$run_id\""
