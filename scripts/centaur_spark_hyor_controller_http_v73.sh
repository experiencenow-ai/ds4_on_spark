#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Start a Centaur v73 HyoR controller HTTP endpoint (human-run; no sudo).

This serves the controller JSON API over HTTP so nodes can use:
  hyor-agent-config-write --transport http --controller-url http://<spark0-host>:8765

Usage:
  centaur_spark_hyor_controller_http_v73.sh [controller_root] [host] [port] [max_requests]

Environment:
  CENTAUR_ROOT   Centaur extracted dir containing centaur.py
               (default: ~/centaur-smoke/v73/run/centaur_spec_impl_v73)
  CENTAUR_VENV   Centaur venv dir containing bin/python3
               (default: ~/centaur-smoke/v73/run/venv)
  HYOR_CONTROLLER_ROOT  Optional explicit controller root override.
  HYOR_RUNTIME_INIT  Set to 1 to run `hyor-runtime-init --force` before serving.
  RING_WORKDIR   When set with RING_RUN_ID, defaults controller_root to:
                $RING_WORKDIR/run/$RING_RUN_ID/controller
  RING_RUN_ID    Ring run id (pairs with RING_WORKDIR).
  CENTAUR_WORKDIR When set (Spark0 smoke), defaults controller_root to:
                $CENTAUR_WORKDIR/hyor/controller
  CENTAUR_RUN_ID When set (Spark0 smoke), defaults controller_root to:
                ~/centaur-smoke/v73/run/$CENTAUR_RUN_ID/hyor/controller

Defaults:
  controller_root: auto (see environment notes above)
  host:            0.0.0.0
  port:            8765
  max_requests:    0 (serve forever)

Example (on Spark0):
  export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
  export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
  sh ./scripts/centaur_spark_hyor_controller_http_v73.sh
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

controller_root="${1:-$(default_controller_root)}"
host="${2:-0.0.0.0}"
port="${3:-8765}"
max_requests="${4:-0}"

centaur_root="${CENTAUR_ROOT:-$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}"
venv_dir="${CENTAUR_VENV:-$HOME/centaur-smoke/v73/run/venv}"

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

echo "== hyor controller-http (v73) =="
echo "controller_root: $controller_root"
echo "listen: http://$host:$port"
echo "max_requests: $max_requests"
echo "runtime_init: ${HYOR_RUNTIME_INIT:-0}"
echo "ctrl-c to stop (max_requests=0 serves forever)"

if [ "${HYOR_RUNTIME_INIT:-0}" = "1" ]; then
	echo "== hyor runtime init (v73) =="
	"$py" -u "$centaur_root/centaur.py" hyor-runtime-init "$controller_root" --force
fi

if [ "$max_requests" = "0" ]; then
	"$py" -u "$centaur_root/centaur.py" hyor-controller-http "$controller_root" --host "$host" --port "$port"
else
	"$py" -u "$centaur_root/centaur.py" hyor-controller-http "$controller_root" --host "$host" --port "$port" --max-requests "$max_requests"
fi
