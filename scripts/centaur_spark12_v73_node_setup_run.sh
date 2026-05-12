#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_node_setup_run.sh <spark1_user@host> <spark2_user@host> [remote_dir] [run_id] [local_out_dir]

Mac-side wrapper to stage + node-setup Spark1 and Spark2 using:
  - scripts/centaur_spark12_v73_stage.sh
  - scripts/centaur_spark_v73_node_setup_run.sh

Remote logs (per node):
  <remote_dir>/run/node_setup/<run_id>/node_setup.log

If local_out_dir is provided, writes local copies of stdout/stderr:
  <local_out_dir>/spark1_node_setup.log
  <local_out_dir>/spark2_node_setup.log

Environment:
  SSH_OPTS                Optional ssh options override (default includes BatchMode + temp known_hosts)
  NODE_SETUP_SKIP_STAGE   Set to 1 to skip staging the zip to Spark1/2
  CENTAUR_PIP_ARGS        Optional extra args for remote pip install (e.g. "--no-index --find-links=/path/to/wheels")
  CENTAUR_SKIP_PIP        Set to 1 to skip remote pip install (assumes venv already has deps)
  CENTAUR_CLEAR_VENV      Set to 1 to pass `--clear` when creating the venv
  CENTAUR_TRACE           Set to 1 to enable remote shell tracing (prints exact commands)

Examples:
  ./scripts/centaur_spark12_v73_node_setup_run.sh spark1@<spark1-host> spark2@<spark2-host>
  ./scripts/centaur_spark12_v73_node_setup_run.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73" 20260512T120000Z /private/tmp/centaur-node-setup/spark12-v73/20260512T120000Z
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
remote_dir="${3:-}"
run_id="${4:-}"
local_out="${5:-}"

if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [ "$local_out" != "" ]; then
	mkdir -p "$local_out"
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
setup_one="$root/scripts/centaur_spark_v73_node_setup_run.sh"
stage12="$root/scripts/centaur_spark12_v73_stage.sh"
if [ ! -x "$setup_one" ]; then
	echo "missing node setup wrapper: $setup_one" >&2
	exit 2
fi
if [ ! -x "$stage12" ]; then
	echo "missing stage12 script: $stage12" >&2
	exit 2
fi

echo "== centaur v73 node setup (spark12) =="
echo "spark1: $spark1"
echo "spark2: $spark2"
echo "remote_dir: $remote_dir"
echo "run_id: $run_id"
if [ "$local_out" != "" ]; then
	echo "local_out_dir: $local_out"
fi

if [ "${NODE_SETUP_SKIP_STAGE:-0}" != "1" ]; then
	"$stage12" "$spark1" "$spark2" "$remote_dir"
else
	echo "== skip stage (NODE_SETUP_SKIP_STAGE=1) =="
fi

log1=""
log2=""
if [ "$local_out" != "" ]; then
	log1="$local_out/spark1_node_setup.log"
	log2="$local_out/spark2_node_setup.log"
fi

NODE_SETUP_SKIP_STAGE=1 "$setup_one" "$spark1" "$remote_dir" "$run_id" "$log1"
NODE_SETUP_SKIP_STAGE=1 "$setup_one" "$spark2" "$remote_dir" "$run_id" "$log2"
