#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_sim_evidence_run.sh <spark0_user@host> [remote_ring_workdir] [local_ring_out_dir]

Runs a full Spark0-local Spark1/Spark2 ring-sim evidence loop from your Mac:
  1) run the Spark0-local ring sim
  2) validate expected ring artifacts on Spark0
  3) fetch a small sanitized artifact bundle back to your Mac

Arguments:
  spark0_user@host     Orchestrator host; must have completed the Spark0 v73 smoke already
  remote_ring_workdir  Optional; default: "~/centaur-smoke/v73/ring_sim_spark12"
  local_ring_out_dir   Optional; default:
                        /private/tmp/centaur-ring-sim/spark12-v73/<ring_run_id>
                        /tmp/centaur-ring-sim/spark12-v73/<ring_run_id>

Environment:
  RING_RUN_ID          Optional ring run id (default: generated UTC timestamp)
  SSH_OPTS             Optional ssh options override (default includes BatchMode + temp known_hosts)

Pass-through env (see underlying scripts):
  CENTAUR_ROOT, CENTAUR_VENV, RING_WORKDIR, RING_LOG, NODE_TYPE, RING_TRACE, RING_SKIP_PREFLIGHT

Notes:
  - This is the rehearsal path before Spark1/2 hardware exists.
  - Requires Mac-side: ssh + (rsync preferred, scp fallback).
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

spark0="$1"
remote_workdir="${2:-}"
local_out="${3:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
run="$root/scripts/centaur_spark12_v73_ring_sim_run.sh"
validate="$root/scripts/centaur_spark12_v73_validate_ring_artifacts.sh"
fetch="$root/scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh"

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd sh
need_cmd ssh
need_cmd mkdir

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

if [ ! -x "$run" ]; then
	echo "missing ring sim runner: $run" >&2
	exit 2
fi
if [ ! -f "$validate" ]; then
	echo "missing ring validate script: $validate" >&2
	exit 2
fi
if [ ! -x "$fetch" ]; then
	echo "missing ring artifact fetcher: $fetch" >&2
	exit 2
fi

run_id="${RING_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [ "$local_out" = "" ]; then
	base="/tmp"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp"
	fi
	local_out="$base/centaur-ring-sim/spark12-v73/$run_id"
fi
mkdir -p "$local_out"
local_log="$local_out/ring_sim.local.log"

echo "== centaur spark12 v73 ring sim evidence run =="
echo "spark0: $spark0"
echo "ring_run_id: $run_id"
echo "remote_ring_workdir: ${remote_workdir:-"(default)"}"
echo "local_ring_out: $local_out"

echo "== step 1/3: run ring sim (Mac wrapper) =="
RING_RUN_ID="$run_id" sh "$run" "$spark0" "$remote_workdir" "$local_log"

echo "== step 2/3: validate ring artifacts (Spark0) =="
ssh $SSH_OPTS "$spark0" "export RING_RUN_ID=\"$run_id\"; sh -s -- --mode sim" < "$validate"

echo "== step 3/3: fetch ring artifacts (Mac) =="
sh "$fetch" "$spark0" "$run_id" "$remote_workdir" "$local_out"

echo "== done =="
echo "ring_run_id: $run_id"
echo "local_ring_out: $local_out"
