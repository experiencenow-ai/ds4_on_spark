#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_rsync_evidence_run.sh <spark0_user@host> <spark1_user@host> <spark2_user@host> [remote_base_dir] [remote_dir] [local_ring_out_dir]

Runs a full Spark1/Spark2 rsync-staged ring evidence loop from your Mac:
  0) (optional) stage + node-setup Spark1/2 (creates Centaur v73 venv + runs selftest)
  1) run the rsync-staged ring-step on Spark0 (streams scripts/centaur_spark_ring_rsync_v73.sh)
  2) validate expected ring artifacts on Spark0
  3) fetch a small sanitized artifact bundle back to your Mac

Arguments:
  spark0_user@host     Orchestrator host; must have completed the Spark0 v73 smoke already
  spark1_user@host     Ring node 1 (for rsync staging)
  spark2_user@host     Ring node 2 (for rsync staging)
  remote_base_dir      Optional; default: "~/centaur-smoke/v73/ring_node"
  remote_dir           Optional; default: "~/centaur-smoke/v73" (used for node setup + staging zip)
  local_ring_out_dir   Optional; default:
                        /private/tmp/centaur-ring/spark12-v73/<ring_run_id>
                        /tmp/centaur-ring/spark12-v73/<ring_run_id>

Environment:
  RING_RUN_ID          Optional ring run id (default: generated UTC timestamp)
  NODE_SETUP_RUN_ID    Optional node setup run id (default: $RING_RUN_ID)
  RING_SKIP_NODE_SETUP Set to 1 to skip Spark1/2 node setup (still stages zip by default)
  SSH_OPTS             Optional ssh options override (default includes BatchMode + temp known_hosts)

Pass-through env (see underlying scripts):
  CENTAUR_PIP_ARGS, CENTAUR_SKIP_PIP, CENTAUR_CLEAR_VENV, CENTAUR_TRACE,
  RING_TRACE, RING_APPLY, RING_SKIP_STAGE, RING_SKIP_PREFLIGHT

Notes:
  - The ring step itself runs on Spark0; Spark1/2 are accessed over SSH for
    rsync staging. No sudo/service changes; no secrets.
  - Node setup is recommended when you want to later run Centaur HTTP agents on
    Spark1/2 (it installs numpy/scipy/scikit-learn and runs selftest).
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
remote_dir="${5:-}"
local_out="${6:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
node_setup="$root/scripts/centaur_spark12_v73_node_setup_run.sh"
node_setup_fetch="$root/scripts/centaur_spark12_v73_node_setup_fetch_logs.sh"
run="$root/scripts/centaur_spark12_v73_ring_rsync_run.sh"
validate="$root/scripts/centaur_spark12_v73_validate_ring_artifacts.sh"
fetch="$root/scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh"

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

if [ ! -x "$node_setup" ]; then
	echo "missing node setup wrapper: $node_setup" >&2
	exit 2
fi
if [ ! -x "$node_setup_fetch" ]; then
	echo "missing node setup log fetcher: $node_setup_fetch" >&2
	exit 2
fi
if [ ! -x "$run" ]; then
	echo "missing ring rsync runner: $run" >&2
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

if [ "$remote_base" = "" ]; then
	remote_base="~/centaur-smoke/v73/ring_node"
fi
if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi

run_id="${RING_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

node_setup_run_id="${NODE_SETUP_RUN_ID:-}"
if [ "$node_setup_run_id" = "" ]; then
	node_setup_run_id="$run_id"
fi

if [ "$local_out" = "" ]; then
	base="/tmp"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp"
	fi
	local_out="$base/centaur-ring/spark12-v73/$run_id"
fi
mkdir -p "$local_out"
local_log="$local_out/ring_rsync.local.log"

echo "== centaur spark12 v73 ring rsync evidence run =="
echo "spark0: $spark0"
echo "spark1: $spark1"
echo "spark2: $spark2"
echo "remote_base: $remote_base"
echo "remote_dir: $remote_dir"
echo "ring_run_id: $run_id"
echo "node_setup_run_id: $node_setup_run_id"
echo "local_ring_out: $local_out"

if [ "${RING_SKIP_NODE_SETUP:-0}" != "1" ]; then
	echo "== step 0/3: node setup (spark1/2) =="
	sh "$node_setup" "$spark1" "$spark2" "$remote_dir" "$node_setup_run_id" "$local_out/node_setup"
	sh "$node_setup_fetch" "$spark1" "$spark2" "$node_setup_run_id" "$remote_dir" "$local_out/node_setup_fetched"
else
	echo "== skip node setup (RING_SKIP_NODE_SETUP=1) =="
fi

echo "== step 1/3: run ring rsync (Mac wrapper) =="
RING_RUN_ID="$run_id" sh "$run" "$spark0" "$spark1" "$spark2" "$remote_base" "$local_log"

echo "== step 2/3: validate ring artifacts (Spark0) =="
ssh $SSH_OPTS "$spark0" "export RING_RUN_ID=\"$run_id\"; sh -s -- --mode rsync" < "$validate"

echo "== step 3/3: fetch ring artifacts (Mac) =="
sh "$fetch" "$spark0" "$run_id" "" "$local_out"

echo "== done =="
echo "ring_run_id: $run_id"
echo "local_ring_out: $local_out"
