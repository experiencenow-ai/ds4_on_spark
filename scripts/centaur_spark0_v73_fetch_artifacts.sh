#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark0_v73_fetch_artifacts.sh <spark0_user@host> <run_id> [remote_dir] [local_out_dir]

Fetch a *small* Centaur Spark0 v73 smoke artifact bundle back to your Mac for bug reports.

Copies (when present) from Spark0:
  - run/<run_id>/smoke.log
  - run/<run_id>/effective_manifests/
  - run/<run_id>/hyor_dashboard/
  - run/<run_id>/hyor_effective/spark0/

Does NOT copy:
  - venvs
  - Centaur source tree
  - controller/node roots (can be large / may contain sensitive hostnames)

Environment:
  SSH_OPTS        Optional ssh options override (default includes BatchMode + temp known_hosts)

Examples:
  ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> 20260511T120827Z
  ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> 20260511T120827Z "~/centaur-smoke/v73" /private/tmp/centaur-smoke/spark0-v73/20260511T120827Z
USAGE
}

case "${1:-}" in
	-h|--help|"")
		usage
		exit 2
		;;
esac

target="$1"
run_id="${2:-}"
if [ "$run_id" = "" ]; then
	usage >&2
	exit 2
fi

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_copy_tool()
{
	if command -v rsync >/dev/null 2>&1; then
		echo "copy_tool: rsync"
		return 0
	fi
	if command -v scp >/dev/null 2>&1; then
		echo "copy_tool: scp"
		return 0
	fi
	echo "missing required command: rsync or scp" >&2
	exit 2
}

remote_dir="${3:-}"
if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi

local_out="${4:-}"
if [ "$local_out" = "" ]; then
	base="/tmp"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp"
	fi
	local_out="$base/centaur-smoke/spark0-v73/$run_id"
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

need_cmd ssh
need_copy_tool

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

copy_from_remote()
{
	remote="$1"
	local_path="$2"
	if command -v rsync >/dev/null 2>&1; then
		rsync -av -e "ssh $SSH_OPTS" "$remote" "$local_path"
		return 0
	fi
	# scp expects a local directory destination for recursive copies
	scp -r $SSH_OPTS "$remote" "$local_path"
}

remote_dir="$(ssh_run "$target" "mkdir -p $remote_dir && cd $remote_dir && pwd -P")"
remote_run_dir="$remote_dir/run/$run_id"

echo "== centaur v73 fetch artifacts =="
echo "target: $target"
echo "run_id: $run_id"
echo "remote_run_dir: $remote_run_dir"
echo "local_out: $local_out"

mkdir -p "$local_out"

if ssh_run "$target" "test -d $remote_run_dir"; then
	:
else
	echo "missing remote run dir: $remote_run_dir" >&2
	exit 2
fi

fetch_one()
{
	remote_path="$1"
	local_path="$2"
	if ssh_run "$target" "test -e $remote_path"; then
		copy_from_remote "$target:$remote_path" "$local_path"
	else
		echo "skip (not found): $remote_path"
	fi
}

fetch_one "$remote_run_dir/smoke.log" "$local_out/"
fetch_one "$remote_run_dir/effective_manifests" "$local_out/"
fetch_one "$remote_run_dir/hyor_dashboard" "$local_out/"
mkdir -p "$local_out/hyor_effective"
fetch_one "$remote_run_dir/hyor_effective/spark0" "$local_out/hyor_effective/"

echo "== done =="
