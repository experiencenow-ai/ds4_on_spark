#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_tp2_readiness.sh -- safe DS4 TP=2 readiness checks

Usage:
  ops_tp2_readiness.sh --self <name> [--peer <host>] [--peer-ssh <user@host>]

Environment:
  SSH_OPTS            Optional ssh options override.
  DS4_WORLD_SIZE      Optional; printed when present.
  DS4_RANK            Optional; printed when present.
  DS4_MASTER_ADDR     Optional; printed when present.
  DS4_MASTER_PORT     Optional; printed when present.

Notes:
  - This script is non-destructive and should not require sudo.
  - It does not modify networking, systemd, or GPU settings.
EOF
}

self=""
peer=""
peer_ssh=""

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

SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/var/tmp/ds4_known_hosts}"

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
[ "${DS4_WORLD_SIZE:-}" != "" ] && echo "DS4_WORLD_SIZE=$DS4_WORLD_SIZE" || true
[ "${DS4_RANK:-}" != "" ] && echo "DS4_RANK=$DS4_RANK" || true
[ "${DS4_MASTER_ADDR:-}" != "" ] && echo "DS4_MASTER_ADDR=$DS4_MASTER_ADDR" || true
[ "${DS4_MASTER_PORT:-}" != "" ] && echo "DS4_MASTER_PORT=$DS4_MASTER_PORT" || true
echo

echo "== gpu =="
nvidia-smi 2>/dev/null || true
command -v nvcc >/dev/null 2>&1 && nvcc --version || true
[ -x /usr/local/cuda/bin/nvcc ] && /usr/local/cuda/bin/nvcc --version || true
echo

echo "== network =="
ip addr 2>/dev/null || true
ip route 2>/dev/null || true
echo

if [ "$peer" != "" ]; then
    echo "== peer ping ($peer) =="
    ping -c 3 "$peer" 2>/dev/null || true
    echo
fi

if [ "$peer_ssh" != "" ]; then
    echo "== peer ssh ($peer_ssh) =="
    ssh $SSH_OPTS "$peer_ssh" hostname 2>/dev/null || true
    echo
fi

echo "== done =="
