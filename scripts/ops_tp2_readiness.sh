#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_tp2_readiness.sh -- safe DS4 TP=2 readiness checks

Usage:
  ops_tp2_readiness.sh --self <name> [--peer <host>] [--peer-ssh <user@host>] [--env <path>]

Environment:
  SSH_OPTS            Optional ssh options override.
  DS4_PEER_HOST       Optional default peer hostname/IP (used if --peer omitted).
  DS4_PEER_SSH        Optional default peer SSH target (used if --peer-ssh omitted).
  DS4_WORLD_SIZE      Optional; printed when present.
  DS4_RANK            Optional; printed when present.
  DS4_MASTER_ADDR     Optional; printed when present.
  DS4_MASTER_PORT     Optional; printed when present.
  DS4_METRICS_ADDR    Optional; printed when present.
  DS4_METRICS_PORT    Optional; printed when present.
  DS4_CONFIG_PATH     Optional; checked for existence when present.

Notes:
  - This script is non-destructive and should not require sudo.
  - It does not modify networking, systemd, or GPU settings.
  - `--env` sources the env file; use only on trusted content.
EOF
}

self=""
peer=""
peer_ssh=""
env_path=""

while [ $# -gt 0 ]; do
    case "$1" in
        --self)
            self="${2:-}"
            shift 2
            ;;
        --peer)
            peer="${2:-}"
            shift 2
            ;;
        --peer-ssh)
            peer_ssh="${2:-}"
            shift 2
            ;;
        --env)
            env_path="${2:-}"
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

if [ "$self" = "" ]; then
    echo "--self is required" >&2
    usage >&2
    exit 2
fi

if [ "$env_path" != "" ]; then
    if [ ! -f "$env_path" ]; then
        echo "missing env file: $env_path" >&2
        exit 2
    fi
    set -a
    # shellcheck disable=SC1090
    . "$env_path"
    set +a
fi

SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/var/tmp/ds4_known_hosts}"

if [ "$peer" = "" ]; then
    peer="${DS4_PEER_HOST:-}"
fi
if [ "$peer_ssh" = "" ]; then
    peer_ssh="${DS4_PEER_SSH:-}"
fi

print_if_set()
{
    key="$1"
    eval "val=\${$key:-}"
    if [ "$val" != "" ]; then
        echo "$key=$val"
    fi
}

check_file()
{
    label="$1"
    path="$2"
    if [ "$path" = "" ]; then
        return 0
    fi
    if [ -f "$path" ]; then
        echo "$label: ok ($path)"
        return 0
    fi
    echo "$label: missing ($path)"
    return 0
}

check_dir_rw()
{
    label="$1"
    path="$2"
    if [ "$path" = "" ]; then
        return 0
    fi
    if [ -d "$path" ]; then
        if [ -r "$path" ] && [ -w "$path" ]; then
            echo "$label: ok rw ($path)"
        else
            echo "$label: not rw ($path)"
        fi
        return 0
    fi
    echo "$label: missing ($path)"
    return 0
}

check_listen()
{
    port="$1"
    label="$2"
    if [ "$port" = "" ]; then
        return 0
    fi
    if command -v ss >/dev/null 2>&1; then
        if ss -lnt 2>/dev/null | awk 'NR>1 {print $4}' | grep -E ":${port}$" >/dev/null 2>&1; then
            echo "$label: listening ($port)"
        else
            echo "$label: not listening ($port)"
        fi
    else
        echo "$label: ss missing; skip ($port)"
    fi
}

echo "== ds4 tp=2 preflight =="
echo "self: $self"
date -Is 2>/dev/null || date || true
echo

echo "== identity =="
hostname || true
id || true
uname -a || true
echo

echo "== time =="
timedatectl status 2>/dev/null || true
echo

echo "== ds4 env (optional) =="
print_if_set DS4_INSTANCE
print_if_set DS4_WORLD_SIZE
print_if_set DS4_RANK
print_if_set DS4_MASTER_ADDR
print_if_set DS4_MASTER_PORT
print_if_set DS4_METRICS_ADDR
print_if_set DS4_METRICS_PORT
print_if_set DS4_CONFIG_PATH
print_if_set DS4_PEER_HOST
print_if_set DS4_PEER_SSH
echo

echo "== ds4 filesystem (optional) =="
check_file "config" "${DS4_CONFIG_PATH:-}"
check_dir_rw "state dir" "${DS4_STATE_DIR:-}"
check_dir_rw "log dir" "${DS4_LOG_DIR:-}"
check_dir_rw "model dir" "${DS4_MODEL_DIR:-}"
check_dir_rw "cache dir" "${DS4_CACHE_DIR:-}"
echo

echo "== ports (optional) =="
check_listen "${DS4_MASTER_PORT:-}" "master port"
check_listen "${DS4_METRICS_PORT:-}" "metrics port"
echo

echo "== gpu =="
nvidia-smi 2>/dev/null || true
command -v nvcc >/dev/null 2>&1 && nvcc --version || true
[ -x /usr/local/cuda/bin/nvcc ] && /usr/local/cuda/bin/nvcc --version || true
echo

echo "== network =="
ip addr 2>/dev/null || true
ip route 2>/dev/null || true
ip link 2>/dev/null || true
echo

if [ "$peer" != "" ]; then
    echo "== peer ping ($peer) =="
    if ping -c 3 "$peer" 2>/dev/null; then
        echo "ping ok"
    else
        echo "ping failed"
    fi
    echo

    if [ "${DS4_MASTER_PORT:-}" != "" ]; then
        echo "== peer tcp check ($peer:$DS4_MASTER_PORT) =="
        if command -v nc >/dev/null 2>&1; then
            if nc -z -w 2 "$peer" "$DS4_MASTER_PORT" 2>/dev/null; then
                echo "tcp ok"
            else
                echo "tcp failed"
            fi
        else
            echo "nc missing; skip tcp check"
        fi
        echo
    fi
fi

if [ "$peer_ssh" != "" ]; then
    echo "== peer ssh ($peer_ssh) =="
    if ssh $SSH_OPTS "$peer_ssh" hostname 2>/dev/null; then
        echo "ssh ok"
    else
        echo "ssh failed (set SSH_OPTS for key/known_hosts if needed)"
    fi
    echo
fi

echo "== done =="
