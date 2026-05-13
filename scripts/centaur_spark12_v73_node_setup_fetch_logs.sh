#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_node_setup_fetch_logs.sh <spark1_user@host> <spark2_user@host> <run_id> [remote_dir] [local_out_dir]

Fetches the remote Spark1/2 node-setup logs created by:
  scripts/centaur_spark12_v73_node_setup_run.sh

Copies (when present) from Spark1 and Spark2:
  - <remote_dir>/run/node_setup/<run_id>/node_setup.log
  - <remote_dir>/run/node_setup/<run_id>/pip_freeze.txt
  - <remote_dir>/run/node_setup/<run_id>/node_setup_facts.json

Environment:
  SSH_OPTS  Optional ssh options override (default includes BatchMode + temp known_hosts)

Defaults:
  remote_dir:   ~/centaur-smoke/v73
  local_out_dir: /private/tmp/centaur-node-setup/spark12-v73/<run_id>/ (or /tmp/... if /private/tmp missing)
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

spark1="$1"
spark2="$2"
run_id="$3"
remote_dir="${4:-}"
local_out="${5:-}"

if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi
if [ "$local_out" = "" ]; then
	base="/tmp"
	if [ -d "/private/tmp" ]; then
		base="/private/tmp"
	fi
	local_out="$base/centaur-node-setup/spark12-v73/$run_id"
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

copy_from_remote()
{
	src="$1"
	dst="$2"
	if command -v rsync >/dev/null 2>&1; then
		rsync -av -e "ssh $SSH_OPTS" "$src" "$dst"
		return 0
	fi
	scp $SSH_OPTS "$src" "$dst"
}

need_cmd ssh
need_copy_tool

mkdir -p "$local_out"

fetch_one()
{
	target="$1"
	label="$2"
	remote_base="$3"

	remote_base="$(ssh $SSH_OPTS "$target" "cd $remote_base && pwd -P")"
	remote_dir_run="$remote_base/run/node_setup/$run_id"
	remote_log="$remote_dir_run/node_setup.log"
	remote_freeze="$remote_dir_run/pip_freeze.txt"
	remote_facts="$remote_dir_run/node_setup_facts.json"
	local_path="$local_out/$label/"
	mkdir -p "$local_path"

	echo "== fetch node setup log: $label =="
	echo "target: $target"
	echo "remote_log: $remote_log"
	echo "local_dir: $local_path"

	if ssh $SSH_OPTS "$target" "test -f $remote_log"; then
		copy_from_remote "$target:$remote_log" "$local_path/"
	else
		echo "skip (not found): $remote_log" >&2
	fi

	if ssh $SSH_OPTS "$target" "test -f $remote_freeze"; then
		copy_from_remote "$target:$remote_freeze" "$local_path/"
	else
		echo "skip (not found): $remote_freeze" >&2
	fi

	if ssh $SSH_OPTS "$target" "test -f $remote_facts"; then
		copy_from_remote "$target:$remote_facts" "$local_path/"
	else
		echo "skip (not found): $remote_facts" >&2
	fi
}

fetch_one "$spark1" "spark1" "$remote_dir"
fetch_one "$spark2" "spark2" "$remote_dir"

echo "== done =="
echo "local_out: $local_out"
