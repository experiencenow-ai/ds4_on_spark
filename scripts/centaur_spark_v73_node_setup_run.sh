#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark_v73_node_setup_run.sh <spark_user@host> [remote_dir] [run_id] [local_log]

Mac-side wrapper to:
  1) Stage Centaur spec-impl v73 zip (and optional catalog fixture) to a Spark node
  2) Stream-run `scripts/centaur_spark_v73_node_setup.sh` on that node

Writes a remote log under:
  <remote_dir>/run/node_setup/<run_id>/node_setup.log

Environment:
  CENTAUR_ZIP             Local zip path (default: /Users/mac/Downloads/centaur_spec_impl_v73.zip)
  CENTAUR_CATALOG_FIXTURE Optional local JSON path to stage as unit_model_catalog.json
  SSH_OPTS                Optional ssh options override (default includes BatchMode + temp known_hosts)
  NODE_SETUP_SKIP_STAGE   Set to 1 to skip staging the zip
  CENTAUR_PIP_ARGS        Optional extra args for remote pip install (e.g. "--no-index --find-links=/path/to/wheels")
  CENTAUR_SKIP_PIP        Set to 1 to skip remote pip install (assumes venv already has deps)
  CENTAUR_CLEAR_VENV      Set to 1 to pass `--clear` when creating the venv
  CENTAUR_TRACE           Set to 1 to enable remote shell tracing (prints exact commands)

Examples:
  ./scripts/centaur_spark_v73_node_setup_run.sh spark1@<spark1-host>
  ./scripts/centaur_spark_v73_node_setup_run.sh spark2@<spark2-host> "~/centaur-smoke/v73" 20260512T120000Z /private/tmp/node_setup_spark2.log
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

target="$1"
remote_dir="${2:-}"
run_id="${3:-}"
local_log="${4:-}"

if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
stage="$root/scripts/centaur_spark_v73_stage.sh"
node_setup="$root/scripts/centaur_spark_v73_node_setup.sh"
if [ ! -x "$stage" ]; then
	echo "missing stage script: $stage" >&2
	exit 2
fi
if [ ! -f "$node_setup" ]; then
	echo "missing node setup script: $node_setup" >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

echo "== centaur v73 node setup run =="
echo "target: $target"
echo "remote_dir: $remote_dir"
echo "run_id: $run_id"
if [ "$local_log" != "" ]; then
	echo "local_log: $local_log"
fi

if [ "${NODE_SETUP_SKIP_STAGE:-0}" != "1" ]; then
	"$stage" "$target" "$remote_dir"
else
	echo "== skip stage (NODE_SETUP_SKIP_STAGE=1) =="
fi

remote_dir="$(ssh $SSH_OPTS "$target" "cd $remote_dir && pwd -P")"
remote_zip="$remote_dir/centaur_spec_impl_v73.zip"
remote_workdir="$remote_dir/run"
remote_log="$remote_workdir/node_setup/$run_id/node_setup.log"

ssh_cmd="cd $remote_dir && export CENTAUR_ZIP=\"$remote_zip\" && export CENTAUR_WORKDIR=\"$remote_workdir\" && export CENTAUR_LOG=\"$remote_log\""
if [ "${CENTAUR_PIP_ARGS:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_PIP_ARGS=\"${CENTAUR_PIP_ARGS}\""
fi
if [ "${CENTAUR_SKIP_PIP:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_SKIP_PIP=\"${CENTAUR_SKIP_PIP}\""
fi
if [ "${CENTAUR_CLEAR_VENV:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_CLEAR_VENV=\"${CENTAUR_CLEAR_VENV}\""
fi
if [ "${CENTAUR_TRACE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_TRACE=\"${CENTAUR_TRACE}\""
fi
ssh_cmd="$ssh_cmd && sh -s"

echo "== run node setup (streamed) =="
echo "ssh $SSH_OPTS $target \"$ssh_cmd\" < $node_setup"
echo "remote_log: $remote_log"

if [ "$local_log" = "" ]; then
	ssh $SSH_OPTS "$target" "$ssh_cmd" < "$node_setup"
else
	ssh $SSH_OPTS "$target" "$ssh_cmd" < "$node_setup" 2>&1 | tee "$local_log"
fi
