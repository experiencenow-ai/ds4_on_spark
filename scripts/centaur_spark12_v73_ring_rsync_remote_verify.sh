#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
usage: centaur_spark12_v73_ring_rsync_remote_verify.sh <spark1_user@host> <spark2_user@host> [remote_base_dir] [remote_dir] [local_out_dir]

Post-ring remote verification helper for the Spark1/Spark2 rsync-staged ring workflow.

This runs from your Mac (or any host with SSH reachability to Spark1/2) and checks:
  - the pushed node roots exist under <remote_base_dir>/hyor/node_spark{1,2}
  - each node can run `centaur.py hyor-sync-status` against its node root

This is intended to validate that Spark1/2 can *locally* inspect the node roots that
Spark0 pushed during `scripts/centaur_spark_ring_rsync_v73.sh`.

Arguments:
  spark1_user@host   Required
  spark2_user@host   Required
  remote_base_dir    Optional; default: "~/centaur-smoke/v73/ring_node"
  remote_dir         Optional; default: "~/centaur-smoke/v73" (expects Centaur venv+root under run/)
  local_out_dir      Optional; writes per-node logs there when set

Environment:
  SSH_OPTS           Optional ssh options override (default includes BatchMode + temp known_hosts)
  RING_REMOTE_TRACE  Set to 1 to enable shell tracing (prints exact commands)

Notes:
  - No sudo/service changes; no secrets.
  - This assumes Spark1/2 have completed node setup at least once so they have:
      <remote_dir>/run/venv/bin/python3
      <remote_dir>/run/centaur_spec_impl_v73/centaur.py
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
remote_base="${3:-}"
remote_dir="${4:-}"
local_out="${5:-}"

if [ "$remote_base" = "" ]; then
	remote_base="~/centaur-smoke/v73/ring_node"
fi
if [ "$remote_dir" = "" ]; then
	remote_dir="~/centaur-smoke/v73"
fi

need_cmd()
{
	if command -v "$1" >/dev/null 2>&1; then
		return 0
	fi
	echo "missing required command: $1" >&2
	exit 2
}

need_cmd ssh
if [ "$local_out" != "" ]; then
	need_cmd mkdir
	mkdir -p "$local_out"
fi

if [ "${SSH_OPTS:-}" = "" ]; then
	known_hosts="/tmp/ds4_spark_known_hosts"
	if [ -d "/private/tmp" ]; then
		known_hosts="/private/tmp/ds4_spark_known_hosts"
	fi
	SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

if [ "${RING_REMOTE_TRACE:-0}" = "1" ]; then
	set -x
fi

ssh_run()
{
	target="$1"
	shift
	ssh $SSH_OPTS "$target" "$@"
}

remote_abs_path()
{
	target="$1"
	path="$2"
	ssh_run "$target" "mkdir -p $path && cd $path && pwd -P"
}

verify_one()
{
	target="$1"
	idx="$2"

	remote_dir_abs="$(remote_abs_path "$target" "$remote_dir")"
	remote_base_abs="$(remote_abs_path "$target" "$remote_base")"
	centaur_root="$remote_dir_abs/run/centaur_spec_impl_v73"
	venv_dir="$remote_dir_abs/run/venv"
	py="$venv_dir/bin/python3"
	node_root="$remote_base_abs/hyor/node_spark$idx"

	echo "== spark$idx remote verify =="
	echo "target: $target"
	echo "remote_dir_abs: $remote_dir_abs"
	echo "remote_base_abs: $remote_base_abs"
	echo "centaur_root: $centaur_root"
	echo "centaur_venv: $venv_dir"
	echo "node_root: $node_root"

	cmd="test -x \"$py\" && test -f \"$centaur_root/centaur.py\" && test -d \"$node_root\" && \"$py\" -u \"$centaur_root/centaur.py\" hyor-sync-status \"$node_root\" --full"

	if [ "$local_out" = "" ]; then
		ssh_run "$target" "$cmd"
	else
		log="$local_out/spark${idx}_remote_verify.log"
		ssh_run "$target" "$cmd" >"$log" 2>&1
		cat "$log"
	fi
}

echo "== centaur spark12 v73 ring rsync remote verify =="
echo "spark1: $spark1"
echo "spark2: $spark2"
echo "remote_base: $remote_base"
echo "remote_dir: $remote_dir"
if [ "$local_out" != "" ]; then
	echo "local_out_dir: $local_out"
fi

verify_one "$spark1" 1
verify_one "$spark2" 2

echo "== done =="

