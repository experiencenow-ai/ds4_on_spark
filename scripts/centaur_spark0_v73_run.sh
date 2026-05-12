#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark0_v73_run.sh <spark0_user@host> [remote_dir] [local_log]

Stages the Centaur spec-impl v73 zip + tiny model catalog fixture to Spark0,
then runs the v73 smoke by streaming `scripts/centaur_spark0_v73_smoke.sh`
over SSH. No sudo/service changes; no secrets; no model weight downloads.

Environment:
  CENTAUR_ZIP        Local zip path (default: /Users/mac/Downloads/centaur_spec_impl_v73.zip)
  SSH_OPTS           Optional ssh options override (default includes BatchMode + temp known_hosts)
  CENTAUR_PIP_ARGS   Optional extra args for remote pip install (e.g. "--no-index --find-links=/path/to/wheels")
  CENTAUR_SKIP_PIP   Set to 1 to skip remote pip install (assumes deps already present in venv)
  CENTAUR_RUN_ID     Optional remote run id (default: generated UTC timestamp)
  CENTAUR_WORKDIR    Optional remote workdir override (default: ~/centaur-smoke/v73/run/$CENTAUR_RUN_ID)
  CENTAUR_TRACE      Set to 1 to enable remote shell tracing (prints exact commands)

Examples:
  ./scripts/centaur_spark0_v73_run.sh spark0@aitopatom-9ab9.local
  ./scripts/centaur_spark0_v73_run.sh spark0@aitopatom-9ab9.local ~/centaur-smoke/v73 /tmp/centaur_spark0_v73_smoke.log

Notes:
  - Artifacts are written under `remote_dir/run/$CENTAUR_RUN_ID/` on Spark0.
  - If local_log is provided, stdout/stderr are tee'd locally.
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
if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi
local_log="${3:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

stage="$root/scripts/centaur_spark0_v73_stage.sh"
smoke="$root/scripts/centaur_spark0_v73_smoke.sh"

if [ ! -x "$stage" ]; then
	echo "missing stage script: $stage" >&2
	exit 2
fi
if [ ! -f "$smoke" ]; then
	echo "missing smoke script: $smoke" >&2
	exit 2
fi

echo "== centaur v73 stage+smoke =="
echo "target: $target"
echo "remote_dir: $remote_dir"
if [ "$local_log" != "" ]; then
	echo "local_log: $local_log"
fi

"$stage" "$target" "$remote_dir"

remote_zip="$remote_dir/centaur_spec_impl_v73.zip"
remote_catalog="$remote_dir/unit_model_catalog.json"

run_id="${CENTAUR_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi
remote_run_dir="$remote_dir/run/$run_id"
remote_smoke_log="$remote_run_dir/smoke.log"

ssh_cmd="cd $remote_dir && mkdir -p $remote_run_dir && export CENTAUR_RUN_ID=\"$run_id\" && export CENTAUR_LOG=\"$remote_smoke_log\" && export CENTAUR_ZIP=\"$remote_zip\" && export CENTAUR_CATALOG_JSON=\"$remote_catalog\""
if [ "${CENTAUR_PIP_ARGS:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_PIP_ARGS=\"${CENTAUR_PIP_ARGS}\""
fi
if [ "${CENTAUR_SKIP_PIP:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_SKIP_PIP=\"${CENTAUR_SKIP_PIP}\""
fi
if [ "${CENTAUR_WORKDIR:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_WORKDIR=\"${CENTAUR_WORKDIR}\""
fi
if [ "${CENTAUR_TRACE:-}" != "" ]; then
	ssh_cmd="$ssh_cmd && export CENTAUR_TRACE=\"${CENTAUR_TRACE}\""
fi
ssh_cmd="$ssh_cmd && sh -s"

echo "== run smoke (streamed) =="
echo "ssh $SSH_OPTS $target \"$ssh_cmd\" < $smoke"
echo "remote_smoke_log: $remote_smoke_log"

if [ "$local_log" = "" ]; then
	ssh $SSH_OPTS "$target" "$ssh_cmd" < "$smoke"
else
	ssh $SSH_OPTS "$target" "$ssh_cmd" < "$smoke" 2>&1 | tee "$local_log"
fi
