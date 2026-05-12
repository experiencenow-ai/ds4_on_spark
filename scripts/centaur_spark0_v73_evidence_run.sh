#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark0_v73_evidence_run.sh <spark0_user@host> [remote_dir] [local_out_dir]

Runs a full Spark0 Centaur spec-impl v73 smoke evidence loop from your Mac:
  1) stage zip + fixture
  2) stream-run the smoke
  3) validate expected artifacts on Spark0
  4) fetch a small sanitized artifact bundle back to your Mac

Arguments:
  spark0_user@host   Required
  remote_dir         Optional; default: "~/centaur-smoke/v73"
  local_out_dir      Optional; default:
                      /private/tmp/centaur-smoke/spark0-v73/<run_id>
                      /tmp/centaur-smoke/spark0-v73/<run_id>

Environment:
  CENTAUR_RUN_ID     Optional run id (default: generated UTC timestamp)
  CENTAUR_ZIP        Local zip path (default used by stage/run scripts)
  SSH_OPTS           Optional ssh options override (default includes BatchMode + temp known_hosts)
  CENTAUR_PIP_ARGS   Optional extra args for remote pip install
  CENTAUR_SKIP_PIP   Set to 1 to skip remote pip install (assumes deps already present in venv)
  CENTAUR_TRACE      Set to 1 to enable remote shell tracing (prints exact commands)

Optional follow-up (after manual redaction review):
  sh ./scripts/centaur_spark0_v73_fixture_pack.sh "<run_id>" "<local_out_dir>"
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
local_out="${3:-}"

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
run="$root/scripts/centaur_spark0_v73_run.sh"
validate="$root/scripts/centaur_spark0_v73_validate_artifacts.sh"
fetch="$root/scripts/centaur_spark0_v73_fetch_artifacts.sh"

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

if [ ! -x "$run" ]; then
	echo "missing run script: $run" >&2
	exit 2
fi
if [ ! -f "$validate" ]; then
	echo "missing validate script: $validate" >&2
	exit 2
fi
if [ ! -x "$fetch" ]; then
	echo "missing fetch script: $fetch" >&2
	exit 2
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi

run_id="${CENTAUR_RUN_ID:-}"
if [ "$run_id" = "" ]; then
	run_id="$(date -u +%Y%m%dT%H%M%SZ)"
fi

if [ "$local_out" = "" ]; then
	base="/tmp"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp"
	fi
	local_out="$base/centaur-smoke/spark0-v73/$run_id"
fi
need_cmd mkdir
mkdir -p "$local_out"
local_log="$local_out/smoke.local.log"

echo "== centaur spark0 v73 evidence run =="
echo "target: $target"
echo "remote_dir: $remote_dir"
echo "run_id: $run_id"
echo "local_out: $local_out"

echo "== step 1/4: run smoke (Mac wrapper) =="
CENTAUR_RUN_ID="$run_id" sh "$run" "$target" "$remote_dir" "$local_log"

echo "== step 2/4: resolve remote workdir =="
remote_dir_abs="$(ssh $SSH_OPTS "$target" "cd $remote_dir && pwd -P")"
remote_workdir="$remote_dir_abs/run/$run_id"
echo "remote_workdir: $remote_workdir"

echo "== step 3/4: validate artifacts (Spark0) =="
ssh $SSH_OPTS "$target" "export CENTAUR_RUN_ID=\"$run_id\"; export CENTAUR_WORKDIR=\"$remote_workdir\"; sh -s" < "$validate"

echo "== step 4/4: fetch artifacts (Mac) =="
sh "$fetch" "$target" "$run_id" "$remote_dir" "$local_out"

echo "== done =="
echo "run_id: $run_id"
echo "local_out: $local_out"
