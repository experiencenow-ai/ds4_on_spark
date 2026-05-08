#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_spark_standalone_check.sh -- safe Spark standalone sanity checks

Usage:
  ops_spark_standalone_check.sh --role <master|worker> --env <path> [--master-host <host>] [--master-port <port>] [--webui-port <port>]

Notes:
  - Non-destructive; does not require sudo.
  - Sources the env file (so do not point at untrusted content).
  - Uses `nc`/`curl` only when installed.
EOF
}

role=""
env_path=""
master_host=""
master_port=""
webui_port=""

while [ $# -gt 0 ]; do
    case "$1" in
        --role)
            role="${2:-}"
            shift 2
            ;;
        --env)
            env_path="${2:-}"
            shift 2
            ;;
        --master-host)
            master_host="${2:-}"
            shift 2
            ;;
        --master-port)
            master_port="${2:-}"
            shift 2
            ;;
        --webui-port)
            webui_port="${2:-}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown arg: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$role" = "" ] || [ "$env_path" = "" ]; then
    usage >&2
    exit 2
fi

if [ ! -f "$env_path" ]; then
    echo "missing env file: $env_path" >&2
    exit 2
fi

set -a
# shellcheck disable=SC1090
. "$env_path"
set +a

err=0

need_nonempty()
{
    key="$1"
    eval "val=\${$key:-}"
    if [ "$val" = "" ]; then
        echo "missing: $key" >&2
        err=1
    fi
}

need_uint()
{
    key="$1"
    eval "val=\${$key:-}"
    case "$val" in
        ''|*[!0-9]*)
            echo "invalid uint: $key=$val" >&2
            err=1
            ;;
    esac
}

echo "== spark standalone check =="
echo "role: $role"
echo "env:  $env_path"
date -Is 2>/dev/null || date || true
echo

need_nonempty SPARK_HOME

need_nonempty SPARK_MASTER_HOST
need_uint SPARK_MASTER_PORT
need_uint SPARK_MASTER_WEBUI_PORT
need_uint SPARK_WORKER_WEBUI_PORT

if [ "$role" = "worker" ]; then
    need_nonempty SPARK_MASTER_URL
fi

if [ "$master_host" = "" ]; then
    master_host="${SPARK_MASTER_HOST:-}"
fi
if [ "$master_port" = "" ]; then
    master_port="${SPARK_MASTER_PORT:-}"
fi
if [ "$webui_port" = "" ]; then
    webui_port="${SPARK_MASTER_WEBUI_PORT:-}"
fi

echo "== identity =="
hostname || true
id || true
uname -a || true
echo

echo "== java =="
command -v java >/dev/null 2>&1 && java -version 2>&1 | head || echo "java missing"
echo

echo "== spark home =="
echo "SPARK_HOME=$SPARK_HOME"
if [ ! -x "$SPARK_HOME/bin/spark-class" ]; then
    echo "missing: $SPARK_HOME/bin/spark-class" >&2
    err=1
fi
echo

echo "== network =="
ip addr 2>/dev/null || true
ip route 2>/dev/null || true
echo

if [ "$master_host" != "" ] && [ "$master_port" != "" ]; then
    echo "== master tcp check ($master_host:$master_port) =="
    if command -v nc >/dev/null 2>&1; then
        nc -z -w 2 "$master_host" "$master_port" 2>/dev/null && echo "tcp ok" || echo "tcp failed"
    else
        echo "nc missing; skip tcp check"
    fi
    echo
fi

if [ "$master_host" != "" ] && [ "$webui_port" != "" ]; then
    echo "== master webui check (http://$master_host:$webui_port) =="
    if command -v curl >/dev/null 2>&1; then
        curl -fsS "http://$master_host:$webui_port/" >/dev/null 2>&1 && echo "http ok" || echo "http failed"
    else
        echo "curl missing; skip http check"
    fi
    echo
fi

if [ "$err" -ne 0 ]; then
    echo "== FAIL ==" >&2
    exit 2
fi

echo "== OK =="

