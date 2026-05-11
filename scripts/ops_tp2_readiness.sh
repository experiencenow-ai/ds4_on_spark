#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_tp2_readiness.sh -- safe DS4 TP=2 readiness checks

Usage:
  ops_tp2_readiness.sh --self <name> [--strict] [--peer <host>] [--peer-ssh <user@host>] [--env <path>]...

Environment:
  SSH_OPTS            Optional ssh options override.
  DS4_PEER_HOST       Optional default peer hostname/IP (used if --peer omitted; required with --strict when DS4_WORLD_SIZE > 1).
  DS4_PEER_SSH        Optional default peer SSH target (used if --peer-ssh omitted).
  DS4_EXPECT_IFACE    Optional expected route interface (e.g. wired NIC). When set, checks the `ip route get` dev for master/peer; mismatch is fatal with --strict.
  DS4_WORLD_SIZE      Optional; printed when present.
  DS4_RANK            Optional; printed when present.
  DS4_MASTER_ADDR     Optional; printed when present.
  DS4_MASTER_PORT     Optional; printed when present.
  DS4_METRICS_ADDR    Optional; printed when present.
  DS4_METRICS_PORT    Optional; printed when present.
  DS4_CONFIG_PATH     Optional; checked for existence when present (required with --strict).

Notes:
  - This script is non-destructive and should not require sudo.
  - It does not modify networking, systemd, or GPU settings.
  - `--strict` exits non-zero when required TP=2 inputs are missing/invalid.
  - `--env` parses env files as simple KEY=VALUE assignments (no shell execution).
  - When `--peer-ssh` (or `DS4_PEER_SSH`) is set, the script also runs a peer→master
    backcheck via SSH using `DS4_MASTER_ADDR`/`DS4_MASTER_PORT` (and optional metrics).
  - Prefix a path with '-' to make it optional (skipped when missing), e.g.:
      ops_tp2_readiness.sh --self spark0 --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env
EOF
}

self=""
peer=""
peer_ssh=""
env_paths=""
strict=0

while [ $# -gt 0 ]; do
    case "$1" in
        --self)
            self="${2:-}"
            shift 2
            ;;
        --strict)
            strict=1
            shift
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
            env_paths="$env_paths ${2:-}"
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

load_env_file()
{
    env_path="$1"
    while IFS= read -r line || [ "$line" != "" ]; do
        case "$line" in
            ''|\#*)
                continue
                ;;
        esac
        line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        case "$line" in
            ''|\#*)
                continue
                ;;
        esac
        case "$line" in
            export\ *)
                line="${line#export }"
                ;;
        esac
        case "$line" in
            *=*)
                key="${line%%=*}"
                val="${line#*=}"
                key="$(printf '%s' "$key" | sed -e 's/[[:space:]]*$//')"
                val="$(printf '%s' "$val" | sed -e 's/^[[:space:]]*//')"
                ;;
            *)
                continue
                ;;
        esac
        case "$key" in
            [A-Za-z_]*)
                ;;
            *)
                continue
                ;;
        esac
        case "$key" in
            *[!A-Za-z0-9_]*)
                continue
                ;;
        esac
        case "$val" in
            \"*\")
                val="${val#\"}"
                val="${val%\"}"
                ;;
            \'*\')
                val="${val#\'}"
                val="${val%\'}"
                ;;
        esac
        export "$key=$val"
    done < "$env_path"
}

if [ "$env_paths" != "" ]; then
    for raw in $env_paths; do
        optional=0
        env_path="$raw"
        case "$raw" in
            -/*)
                optional=1
                env_path="${raw#-}"
                ;;
        esac
        if [ ! -f "$env_path" ]; then
            if [ "$optional" -ne 0 ]; then
                continue
            fi
            echo "missing env file: $env_path" >&2
            exit 2
        fi
        if [ ! -r "$env_path" ]; then
            echo "unreadable env file (check owner/group/mode): $env_path" >&2
            exit 2
        fi
        load_env_file "$env_path"
    done
fi

if [ "${SSH_OPTS:-}" = "" ]; then
    known_hosts="/var/lib/ds4/ssh/known_hosts"
    if [ ! -d "/var/lib/ds4/ssh" ]; then
        known_hosts="/var/tmp/ds4_known_hosts"
    fi
    SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

if [ "$peer" = "" ]; then
    peer="${DS4_PEER_HOST:-}"
fi
if [ "$peer_ssh" = "" ]; then
    peer_ssh="${DS4_PEER_SSH:-}"
fi

is_uint()
{
    case "${1:-}" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac
    return 0
}

validate_port()
{
    key="$1"
    val="$2"
    if [ "$val" = "" ]; then
        return 0
    fi
    if ! is_uint "$val"; then
        echo "$key must be an integer: $val" >&2
        return 1
    fi
    if [ "$val" -lt 1 ] || [ "$val" -gt 65535 ]; then
        echo "$key out of range (1-65535): $val" >&2
        return 1
    fi
    return 0
}

strict_validate()
{
    fail=0

    if [ "${DS4_CONFIG_PATH:-}" = "" ]; then
        echo "strict: DS4_CONFIG_PATH is required" >&2
        fail=1
    else
        if [ ! -f "$DS4_CONFIG_PATH" ]; then
            echo "strict: config missing: $DS4_CONFIG_PATH" >&2
            fail=1
        elif [ ! -r "$DS4_CONFIG_PATH" ]; then
            echo "strict: config unreadable: $DS4_CONFIG_PATH" >&2
            fail=1
        else
            scripts_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
            if [ -x "$scripts_dir/ops_ds4_config_check.sh" ]; then
                if ! "$scripts_dir/ops_ds4_config_check.sh" --strict-unknown "$DS4_CONFIG_PATH" >/dev/null 2>&1; then
                    echo "strict: invalid ds4 config: $DS4_CONFIG_PATH" >&2
                    "$scripts_dir/ops_ds4_config_check.sh" --strict-unknown "$DS4_CONFIG_PATH" >&2 || true
                    fail=1
                fi
            fi
        fi
    fi

    if [ "${DS4_MASTER_ADDR:-}" = "" ]; then
        echo "strict: DS4_MASTER_ADDR is required" >&2
        fail=1
    fi

    if [ "${DS4_MASTER_PORT:-}" = "" ]; then
        echo "strict: DS4_MASTER_PORT is required" >&2
        fail=1
    else
        validate_port "DS4_MASTER_PORT" "$DS4_MASTER_PORT" || fail=1
    fi

    if [ "${DS4_METRICS_PORT:-}" != "" ]; then
        validate_port "DS4_METRICS_PORT" "$DS4_METRICS_PORT" || fail=1
    fi
    if [ "${DS4_MASTER_PORT:-}" != "" ] && [ "${DS4_METRICS_PORT:-}" != "" ]; then
        if [ "$DS4_MASTER_PORT" = "$DS4_METRICS_PORT" ]; then
            echo "strict: DS4_MASTER_PORT and DS4_METRICS_PORT must differ: $DS4_MASTER_PORT" >&2
            fail=1
        fi
    fi

    if [ "${DS4_WORLD_SIZE:-}" = "" ]; then
        echo "strict: DS4_WORLD_SIZE is required" >&2
        fail=1
    elif ! is_uint "$DS4_WORLD_SIZE"; then
        echo "strict: DS4_WORLD_SIZE must be an integer: $DS4_WORLD_SIZE" >&2
        fail=1
    fi

    if [ "${DS4_RANK:-}" = "" ]; then
        echo "strict: DS4_RANK is required" >&2
        fail=1
    elif ! is_uint "$DS4_RANK"; then
        echo "strict: DS4_RANK must be an integer: $DS4_RANK" >&2
        fail=1
    fi

    if is_uint "${DS4_WORLD_SIZE:-}" && is_uint "${DS4_RANK:-}"; then
        if [ "$DS4_WORLD_SIZE" -le 0 ]; then
            echo "strict: DS4_WORLD_SIZE must be > 0: $DS4_WORLD_SIZE" >&2
            fail=1
        fi
        if [ "$DS4_RANK" -ge "$DS4_WORLD_SIZE" ]; then
            echo "strict: DS4_RANK must be < DS4_WORLD_SIZE ($DS4_RANK >= $DS4_WORLD_SIZE)" >&2
            fail=1
        fi
        if [ "$DS4_WORLD_SIZE" -gt 1 ]; then
            case "${DS4_MASTER_ADDR:-}" in
                127.0.0.1|localhost|\:\:1|0.0.0.0|\:\:|\[\:\:\])
                    echo "strict: DS4_MASTER_ADDR looks local/wildcard for DS4_WORLD_SIZE=$DS4_WORLD_SIZE: ${DS4_MASTER_ADDR}" >&2
                    fail=1
                    ;;
            esac
            if [ "${DS4_PEER_HOST:-}" = "" ]; then
                echo "strict: DS4_PEER_HOST is required for DS4_WORLD_SIZE=$DS4_WORLD_SIZE" >&2
                fail=1
            fi
        fi
    fi

    if [ "$fail" -ne 0 ]; then
        return 1
    fi
    return 0
}

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
        if [ -r "$path" ]; then
            echo "$label: ok ($path)"
        else
            echo "$label: unreadable ($path)"
        fi
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

metrics_url_host()
{
    host="${1:-}"
    if [ "$host" = "" ] || [ "$host" = "0.0.0.0" ]; then
        host="127.0.0.1"
    fi
    case "$host" in
        \[*\])
            echo "$host"
            return 0
            ;;
        *:*)
            echo "[$host]"
            return 0
            ;;
    esac
    echo "$host"
    return 0
}

check_metrics_endpoint()
{
    addr="${1:-}"
    port="${2:-}"
    if [ "$port" = "" ]; then
        echo "metrics: skip (DS4_METRICS_PORT unset)"
        return 0
    fi
    host="$(metrics_url_host "$addr")"
    if command -v curl >/dev/null 2>&1; then
        if curl -fsS --max-time 2 "http://${host}:${port}/metrics" >/dev/null 2>&1; then
            echo "metrics: http ok (${host}:${port})"
        else
            echo "metrics: http failed (${host}:${port})"
        fi
        return 0
    fi
    echo "metrics: curl missing; skip (${host}:${port})"
    return 0
}

check_peer_metrics_endpoint()
{
    peer_host="${1:-}"
    port="${2:-}"
    if [ "$peer_host" = "" ] || [ "$port" = "" ]; then
        echo "peer metrics: skip"
        return 0
    fi
    host="$(metrics_url_host "$peer_host")"
    if command -v curl >/dev/null 2>&1; then
        if curl -fsS --max-time 2 "http://${host}:${port}/metrics" >/dev/null 2>&1; then
            echo "peer metrics: http ok (${host}:${port})"
        else
            echo "peer metrics: http failed (${host}:${port})"
        fi
        return 0
    fi
    echo "peer metrics: curl missing; skip (${host}:${port})"
    return 0
}

is_ipv4()
{
    v="${1:-}"
    if [ "$v" = "" ]; then
        return 1
    fi
    case "$v" in
        *[!0-9.]*)
            return 1
            ;;
        *.*.*.*)
            return 0
            ;;
    esac
    return 1
}

resolve_ipv4_best_effort()
{
    host="${1:-}"
    if [ "$host" = "" ]; then
        return 1
    fi
    if is_ipv4 "$host"; then
        echo "$host"
        return 0
    fi
    if command -v getent >/dev/null 2>&1; then
        ip="$(getent ahostsv4 "$host" 2>/dev/null | awk 'NR==1 {print $1}')"
        if [ "${ip:-}" != "" ]; then
            echo "$ip"
            return 0
        fi
        ip="$(getent hosts "$host" 2>/dev/null | awk 'NR==1 {print $1}')"
        if [ "${ip:-}" != "" ]; then
            echo "$ip"
            return 0
        fi
    fi
    return 1
}

print_host_resolution()
{
    label="$1"
    host="${2:-}"
    if [ "$host" = "" ]; then
        return 0
    fi

    echo "$label: $host"

    ip="$(resolve_ipv4_best_effort "$host" 2>/dev/null || true)"
    if [ "$ip" != "" ] && [ "$ip" != "$host" ]; then
        echo "$label ipv4: $ip"
    fi

    route_ip="$host"
    if [ "$ip" != "" ]; then
        route_ip="$ip"
    fi

    if command -v ip >/dev/null 2>&1; then
        if is_ipv4 "$route_ip"; then
            route="$(ip -4 route get "$route_ip" 2>/dev/null | sed -n '1p' || true)"
            if [ "${route:-}" != "" ]; then
                echo "$label route: $route"
            fi
        fi
    fi

    return 0
}

route_dev_for_host_best_effort()
{
    host="${1:-}"
    if [ "$host" = "" ]; then
        return 1
    fi
    ip="$(resolve_ipv4_best_effort "$host" 2>/dev/null || true)"
    route_ip="$host"
    if [ "$ip" != "" ]; then
        route_ip="$ip"
    fi
    if command -v ip >/dev/null 2>&1; then
        if is_ipv4 "$route_ip"; then
            route="$(ip -4 route get "$route_ip" 2>/dev/null | sed -n '1p' || true)"
            if [ "${route:-}" != "" ]; then
                dev="$(printf '%s\n' "$route" | awk '{for (i=1; i<=NF; i++) if ($i=="dev") {print $(i+1); exit}}' 2>/dev/null || true)"
                if [ "${dev:-}" != "" ]; then
                    echo "$dev"
                    return 0
                fi
            fi
        fi
    fi
    return 1
}

check_expected_iface()
{
    label="$1"
    host="${2:-}"
    expected="${DS4_EXPECT_IFACE:-}"
    if [ "$expected" = "" ] || [ "$host" = "" ]; then
        return 0
    fi

    dev="$(route_dev_for_host_best_effort "$host" 2>/dev/null || true)"
    if [ "$dev" = "" ]; then
        echo "iface: skip ($label; route dev unknown for $host)"
        return 0
    fi

    if [ "$dev" = "$expected" ]; then
        echo "iface: ok ($label; dev=$dev)"
        return 0
    fi

    if [ "$strict" -ne 0 ]; then
        echo "iface: mismatch ($label; expected=$expected got=$dev host=$host)" >&2
        return 1
    fi
    echo "iface: mismatch ($label; expected=$expected got=$dev host=$host)"
    return 0
}

peer_backcheck_via_ssh()
{
    target="$1"
    master_addr="${2:-}"
    master_port="${3:-}"
    metrics_port="${4:-}"

    if [ "$master_addr" = "" ]; then
        echo "peer backcheck: skip (DS4_MASTER_ADDR unset)"
        return 0
    fi

    if ssh $SSH_OPTS "$target" sh -c '
set -eu
master_addr="${1:-}"
master_port="${2:-}"
metrics_port="${3:-}"
echo "peer host: $(hostname 2>/dev/null || true)"
echo "peer -> master: $master_addr"
if ping -c 2 "$master_addr" 2>/dev/null; then
    echo "master ping: ok"
else
    echo "master ping: failed"
fi
if [ "$master_port" != "" ]; then
    if command -v nc >/dev/null 2>&1; then
        if nc -z -w 2 "$master_addr" "$master_port" 2>/dev/null; then
            echo "master tcp ($master_port): ok"
        else
            echo "master tcp ($master_port): failed"
        fi
    else
        echo "master tcp: nc missing; skip ($master_port)"
    fi
fi
if [ "$metrics_port" != "" ]; then
    if command -v curl >/dev/null 2>&1; then
        host="$master_addr"
        case "$host" in
            \[*\])
                ;;
            *:*)
                host="[$host]"
                ;;
        esac
        if curl -fsS --max-time 2 "http://${host}:${metrics_port}/metrics" >/dev/null 2>&1; then
            echo "master metrics: http ok (${host}:${metrics_port})"
        else
            echo "master metrics: http failed (${host}:${metrics_port})"
        fi
    else
        echo "master metrics: curl missing; skip ($metrics_port)"
    fi
fi
' sh "$master_addr" "$master_port" "$metrics_port" 2>/dev/null; then
        echo "peer ssh: ok"
    else
        echo "peer ssh: failed (set SSH_OPTS for key/known_hosts if needed)"
    fi
    return 0
}

echo "== ds4 tp=2 preflight =="
echo "self: $self"
date -Is 2>/dev/null || date || true
echo

echo "== identity =="
hostname || true
id || true
uname -a || true
ulimit -n 2>/dev/null || true
echo

echo "== time =="
timedatectl status 2>/dev/null || true
if command -v timedatectl >/dev/null 2>&1; then
    synced="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
    if [ "${synced:-}" != "" ]; then
        echo "NTPSynchronized=$synced"
    fi
fi
echo

if [ "$strict" -ne 0 ]; then
    echo "== strict env validation =="
    if strict_validate; then
        echo "strict ok"
    else
        echo "strict failed" >&2
        exit 1
    fi
    echo
fi

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
print_if_set DS4_EXPECT_IFACE
echo

echo "== host resolution + routes (best effort) =="
print_host_resolution "master" "${DS4_MASTER_ADDR:-}"
if [ "$peer" != "" ]; then
    print_host_resolution "peer" "$peer"
else
    print_host_resolution "peer" "${DS4_PEER_HOST:-}"
fi
echo

echo "== route iface check (optional) =="
if [ "${DS4_EXPECT_IFACE:-}" = "" ]; then
    echo "iface: skip (DS4_EXPECT_IFACE unset)"
else
    check_expected_iface "master" "${DS4_MASTER_ADDR:-}" || exit 1
    if [ "$peer" != "" ]; then
        check_expected_iface "peer" "$peer" || exit 1
    else
        check_expected_iface "peer" "${DS4_PEER_HOST:-}" || exit 1
    fi
fi
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

echo "== metrics endpoint (optional) =="
check_metrics_endpoint "${DS4_METRICS_ADDR:-}" "${DS4_METRICS_PORT:-}"
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
    echo "== peer metrics endpoint (optional) =="
    check_peer_metrics_endpoint "$peer" "${DS4_METRICS_PORT:-}"
    echo

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
    peer_backcheck_via_ssh "$peer_ssh" "${DS4_MASTER_ADDR:-}" "${DS4_MASTER_PORT:-}" "${DS4_METRICS_PORT:-}"
    echo
fi

echo "== done =="
