#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'USAGE'
Start a Centaur v73 HyoR node agent HTTP endpoint (human-run; no sudo).

This writes an HTTP-configured node agent config (transport=http) and then
serves the node agent endpoint over HTTP so the controller can:
  hyor-node-discover <controller_root> --seed-url http://<node-host>:8766 ...

Usage:
  centaur_spark_hyor_agent_http_v73.sh <node_root> <node_id> <controller_url> [host] [port] [max_requests]

Environment:
  CENTAUR_ROOT      Centaur extracted dir containing centaur.py
                  (default: ~/centaur-smoke/v73/run/centaur_spec_impl_v73)
  CENTAUR_VENV      Centaur venv dir containing bin/python3
                  (default: ~/centaur-smoke/v73/run/venv)
  NODE_TYPE         Node type label (default: default)
  EFFECTIVE_DIR     Optional effective output dir to materialize on each agent step
  AUTH_TOKEN_ENV    Optional auth token env var name for controller/node HTTP (name only; value is never printed)
  HTTP_TIMEOUT_S    HTTP timeout seconds for node->controller calls (default: 5)

Defaults:
  host:         0.0.0.0
  port:         8766
  max_requests: 0 (serve forever)

Example (on Spark1):
  export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
  export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
  export CONTROLLER_URL="http://<spark0-host>:8765"
  sh ./scripts/centaur_spark_hyor_agent_http_v73.sh ~/centaur-smoke/v73/ring_node/hyor/node_spark1 spark1 "$CONTROLLER_URL" 0.0.0.0 8766

Notes:
  - This is intended as a smoke endpoint (no secrets, no model downloads).
  - Avoid enabling ring sync on the node: peer roots are filesystem paths and
    may not be meaningful on the remote host.
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

node_root="$1"
node_id="$2"
controller_url="$3"
host="${4:-0.0.0.0}"
port="${5:-8766}"
max_requests="${6:-0}"

centaur_root="${CENTAUR_ROOT:-$HOME/centaur-smoke/v73/run/centaur_spec_impl_v73}"
venv_dir="${CENTAUR_VENV:-$HOME/centaur-smoke/v73/run/venv}"
node_type="${NODE_TYPE:-default}"
effective_dir="${EFFECTIVE_DIR:-}"
auth_env="${AUTH_TOKEN_ENV:-}"
timeout_s="${HTTP_TIMEOUT_S:-5}"

if [ ! -f "$centaur_root/centaur.py" ]; then
	echo "missing centaur.py under CENTAUR_ROOT: $centaur_root" >&2
	exit 2
fi
py="$venv_dir/bin/python3"
if [ ! -x "$py" ]; then
	echo "missing venv python3 under CENTAUR_VENV: $venv_dir" >&2
	exit 2
fi

mkdir -p "$node_root"
if [ "$effective_dir" != "" ]; then
	mkdir -p "$effective_dir"
fi

echo "== hyor agent-http (v73) =="
echo "node_root: $node_root"
echo "node_id: $node_id"
echo "node_type: $node_type"
echo "controller_url: $controller_url"
echo "listen: http://$host:$port"
echo "max_requests: $max_requests"
if [ "$effective_dir" != "" ]; then
	echo "effective_dir: $effective_dir"
fi

centaur()
{
	"$py" -u "$centaur_root/centaur.py" "$@"
}

set -- hyor-agent-config-write "$node_root" --node-id "$node_id" --node-type "$node_type" --transport http --controller-url "$controller_url" --allow-no-executor --no-internet --force --notes ring-http-smoke-v73
if [ "$effective_dir" != "" ]; then
	set -- "$@" --effective-output-dir "$effective_dir"
fi
if [ "$auth_env" != "" ]; then
	set -- "$@" --auth-token-env "$auth_env"
fi
if [ "$timeout_s" != "" ]; then
	set -- "$@" --http-timeout-seconds "$timeout_s"
fi
centaur "$@"

if [ "$auth_env" = "" ]; then
	if [ "$max_requests" = "0" ]; then
		centaur hyor-agent-http "$node_root" --host "$host" --port "$port"
	else
		centaur hyor-agent-http "$node_root" --host "$host" --port "$port" --max-requests "$max_requests"
	fi
else
	if [ "$max_requests" = "0" ]; then
		centaur hyor-agent-http "$node_root" --host "$host" --port "$port" --auth-env "$auth_env"
	else
		centaur hyor-agent-http "$node_root" --host "$host" --port "$port" --auth-env "$auth_env" --max-requests "$max_requests"
	fi
fi
