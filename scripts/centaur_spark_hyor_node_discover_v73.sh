#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Discover/register Spark nodes via their Centaur v73 agent HTTP endpoints.

This runs on the controller host (typically Spark0) and calls:
  centaur.py hyor-node-discover <controller_root> --seed-url ...

Usage:
  centaur_spark_hyor_node_discover_v73.sh [controller_root] <seed_url> [seed_url...]

Environment:
  CENTAUR_ROOT     Centaur extracted dir containing centaur.py
                 (default: ~/centaur-smoke/v73/run/centaur_spec_impl_v73)
  CENTAUR_VENV     Centaur venv dir containing bin/python3
                 (default: ~/centaur-smoke/v73/run/venv)
  HYOR_CONTROLLER_ROOT  Optional explicit controller root override.
  RING_WORKDIR     When set with RING_RUN_ID, defaults controller_root to:
                  $RING_WORKDIR/run/$RING_RUN_ID/controller
  RING_RUN_ID      Ring run id (pairs with RING_WORKDIR).
  CENTAUR_WORKDIR  When set (Spark0 smoke), defaults controller_root to:
                  $CENTAUR_WORKDIR/hyor/controller
  CENTAUR_RUN_ID   When set (Spark0 smoke), defaults controller_root to:
                  ~/centaur-smoke/v73/run/$CENTAUR_RUN_ID/hyor/controller
  AUTH_TOKEN_ENV   Optional auth token env var name for controller/node HTTP
  TIMEOUT_S        HTTP timeout seconds (default: 5)
  WORKERS          Concurrent probe workers (default: 8)
  NO_APPLY         Set to 1 to probe without applying discoveries to controller state

Default controller_root:
  auto (see environment notes above)

Example (on Spark0):
  export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
  export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
  export RING_WORKDIR=~/centaur-smoke/v73/ring_rsync_spark12
  export RING_RUN_ID=<ring_run_id>
  sh ./scripts/centaur_spark_hyor_node_discover_v73.sh http://<spark1-host>:8766 http://<spark2-host>:8767
USAGE
}

case "${1:-}" in
	-h|--help)
		usage
		exit 0
		;;
esac

default_controller_root()
{
	if [ "${HYOR_CONTROLLER_ROOT:-}" != "" ]; then
		echo "$HYOR_CONTROLLER_ROOT"
		return 0
	fi
	if [ "${RING_WORKDIR:-}" != "" ] && [ "${RING_RUN_ID:-}" != "" ]; then
		echo "${RING_WORKDIR%/}/run/$RING_RUN_ID/controller"
		return 0
	fi
	if [ "${CENTAUR_WORKDIR:-}" != "" ]; then
		echo "${CENTAUR_WORKDIR%/}/hyor/controller"
		return 0
	fi
	if [ "${CENTAUR_RUN_ID:-}" != "" ]; then
		echo "$HOME/centaur-smoke/v73/run/$CENTAUR_RUN_ID/hyor/controller"
		return 0
	fi
	echo "$HOME/centaur-smoke/v73/run/hyor/controller"
	return 0
}

first="${1:-}"
controller_root="$(default_controller_root)"
seed_urls=""
case "$first" in
	http://*|https://*)
		seed_urls="$*"
		;;
	"")
		usage >&2
		exit 2
		;;
	*)
		controller_root="$1"
		shift
		seed_urls="$*"
		;;
esac

if [ "$seed_urls" = "" ]; then
	echo "missing seed_url arguments" >&2
	usage >&2
	exit 2
fi

centaur_root="${CENTAUR_ROOT:-$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}"
venv_dir="${CENTAUR_VENV:-$HOME/centaur-smoke/v73/run/venv}"
auth_env="${AUTH_TOKEN_ENV:-}"
timeout_s="${TIMEOUT_S:-5}"
workers="${WORKERS:-8}"
no_apply="${NO_APPLY:-0}"

if [ ! -f "$centaur_root/centaur.py" ]; then
	echo "missing centaur.py under CENTAUR_ROOT: $centaur_root" >&2
	exit 2
fi
py="$venv_dir/bin/python3"
if [ ! -x "$py" ]; then
	echo "missing venv python3 under CENTAUR_VENV: $venv_dir" >&2
	exit 2
fi

mkdir -p "$controller_root"

echo "== hyor node discover (v73) =="
echo "controller_root: $controller_root"
echo "timeout_s: $timeout_s"
echo "workers: $workers"
echo "no_apply: $no_apply"

centaur()
{
	"$py" -u "$centaur_root/centaur.py" "$@"
}

set -- hyor-node-discover "$controller_root" --timeout-seconds "$timeout_s" --workers "$workers"
if [ "$no_apply" = "1" ]; then
	set -- "$@" --no-apply
fi
if [ "$auth_env" != "" ]; then
	set -- "$@" --auth-env "$auth_env"
fi
for url in $seed_urls; do
	set -- "$@" --seed-url "$url"
done
centaur "$@"
