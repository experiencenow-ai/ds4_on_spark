#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_tp3_readiness.sh -- safe DS4 TP=3 readiness checks (Spark0/Spark1/Spark2)

Usage:
  ops_tp3_readiness.sh --self <name> [--topology ring|full] [--strict] [--hosts <h0,h1,h2>] [--tcp <port>]... [--env <path>]...

Environment:
  SSH_OPTS            Optional ssh options override.
  DS4_RING_HOSTS      Optional comma-separated hosts in rank order: h0,h1,h2.
  DS4_EXPECT_IFACE    Optional expected route interface (e.g. wired NIC). When set,
                      checks the `ip route get` dev for master + selected peers;
                      mismatch is fatal with --strict.
  DS4_WORLD_SIZE      Optional; strict requires 3.
  DS4_RANK            Optional; strict requires 0..2 and used to pick ring neighbors.
  DS4_MASTER_ADDR     Optional; strict requires when DS4_WORLD_SIZE > 1.
  DS4_MASTER_PORT     Optional; strict requires when DS4_WORLD_SIZE > 1.
  DS4_METRICS_ADDR    Optional; printed when present.
  DS4_METRICS_PORT    Optional; validated when present.
  DS4_PEER_HOST       Optional default peer hostname/IP for best-effort SSH backchecks.
  DS4_PEER_SSH        Optional peer SSH target (used for optional peer→master backcheck).

Notes:
  - This script is non-destructive and should not require sudo.
  - It does not modify networking, systemd, or GPU settings.
  - `--env` parses env files as simple KEY=VALUE assignments (no shell execution).
  - With `--topology ring` (default), the script checks only the rank-adjacent
    neighbors (prev/next) from DS4_RING_HOSTS. With `--topology full`, it checks
    all other ranks.
EOF
}

self=""
topology="ring"
strict=0
hosts_csv=""
tcp_ports=""
env_paths=""

while [ $# -gt 0 ]; do
    case "$1" in
        --self)
            self="${2:-}"
            shift 2
            ;;
        --topology)
            topology="${2:-}"
            shift 2
            ;;
        --strict)
            strict=1
            shift
            ;;
        --hosts)
            hosts_csv="${2:-}"
            shift 2
            ;;
        --tcp)
            tcp_ports="$tcp_ports ${2:-}"
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

case "$topology" in
    ring|full)
        ;;
    *)
        echo "invalid --topology: $topology (expected ring|full)" >&2
        exit 2
        ;;
esac

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
        cache_root="${XDG_CACHE_HOME:-${HOME:-}/.cache}"
        if [ "${HOME:-}" != "" ] && [ -d "$HOME" ] && [ "$cache_root" != "/.cache" ]; then
            cache_dir="$cache_root/ds4/ssh"
            if mkdir -p "$cache_dir" 2>/dev/null; then
                known_hosts="$cache_dir/known_hosts"
            else
                known_hosts="/var/tmp/ds4_known_hosts"
            fi
        else
            known_hosts="/var/tmp/ds4_known_hosts"
        fi
    fi
    SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
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

trim_ws()
{
    printf '%s' "${1:-}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
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
    host="$2"
    expect="${DS4_EXPECT_IFACE:-}"
    if [ "$expect" = "" ] || [ "$host" = "" ]; then
        return 0
    fi
    dev="$(route_dev_for_host_best_effort "$host" 2>/dev/null || true)"
    if [ "$dev" = "" ]; then
        echo "$label iface: skip (route dev unknown for $host)"
        return 0
    fi
    if [ "$dev" = "$expect" ]; then
        echo "$label iface: ok ($dev)"
        return 0
    fi
    echo "$label iface: mismatch (got=$dev expect=$expect)" >&2
    if [ "$strict" -ne 0 ]; then
        return 1
    fi
    return 0
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
    label="$1"
    peer_host="${2:-}"
    port="${3:-}"
    if [ "$peer_host" = "" ] || [ "$port" = "" ]; then
        echo "$label metrics: skip"
        return 0
    fi
    host="$(metrics_url_host "$peer_host")"
    if command -v curl >/dev/null 2>&1; then
        if curl -fsS --max-time 2 "http://${host}:${port}/metrics" >/dev/null 2>&1; then
            echo "$label metrics: http ok (${host}:${port})"
        else
            echo "$label metrics: http failed (${host}:${port})"
        fi
        return 0
    fi
    echo "$label metrics: curl missing; skip (${host}:${port})"
    return 0
}

tcp_probe_best_effort()
{
    label="$1"
    host="${2:-}"
    if [ "$host" = "" ]; then
        return 0
    fi
    if [ "$tcp_ports" = "" ]; then
        echo "$label tcp: skip"
        return 0
    fi
    if command -v nc >/dev/null 2>&1; then
        for p in $tcp_ports; do
            if [ "$p" = "" ]; then
                continue
            fi
            if nc -z -w 2 "$host" "$p" 2>/dev/null; then
                echo "$label tcp: ok (${host}:${p})"
            else
                echo "$label tcp: failed (${host}:${p})"
            fi
        done
        return 0
    fi
    echo "$label tcp: nc missing; skip"
    return 0
}

hosts_unique()
{
    h0="$1"
    h1="$2"
    h2="$3"
    if [ "$h0" = "$h1" ] || [ "$h0" = "$h2" ] || [ "$h1" = "$h2" ]; then
        return 1
    fi
    return 0
}

strict_validate()
{
    fail=0
    csv=""
    h0=""
    h1=""
    h2=""

    if [ "${DS4_WORLD_SIZE:-}" = "" ]; then
        echo "strict: DS4_WORLD_SIZE is required" >&2
        fail=1
    elif ! is_uint "$DS4_WORLD_SIZE"; then
        echo "strict: DS4_WORLD_SIZE must be an integer: $DS4_WORLD_SIZE" >&2
        fail=1
    elif [ "$DS4_WORLD_SIZE" -ne 3 ]; then
        echo "strict: DS4_WORLD_SIZE must be 3 for TP=3: $DS4_WORLD_SIZE" >&2
        fail=1
    fi

    if [ "${DS4_RANK:-}" = "" ]; then
        echo "strict: DS4_RANK is required" >&2
        fail=1
    elif ! is_uint "$DS4_RANK"; then
        echo "strict: DS4_RANK must be an integer: $DS4_RANK" >&2
        fail=1
    elif [ "$DS4_RANK" -gt 2 ]; then
        echo "strict: DS4_RANK out of range for TP=3 (0..2): $DS4_RANK" >&2
        fail=1
    fi

    if [ "${DS4_MASTER_ADDR:-}" = "" ]; then
        echo "strict: DS4_MASTER_ADDR is required" >&2
        fail=1
    else
        case "${DS4_MASTER_ADDR:-}" in
            127.0.0.1|localhost|\:\:1|0.0.0.0|\:\:|\[\:\:\])
                echo "strict: DS4_MASTER_ADDR looks local/wildcard for TP=3: ${DS4_MASTER_ADDR}" >&2
                fail=1
                ;;
        esac
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

    if [ "$hosts_csv" = "" ] && [ "${DS4_RING_HOSTS:-}" = "" ]; then
        echo "strict: provide --hosts or DS4_RING_HOSTS (comma-separated h0,h1,h2)" >&2
        fail=1
    else
        csv="$hosts_csv"
        if [ "$csv" = "" ]; then
            csv="${DS4_RING_HOSTS:-}"
        fi
        set -- $(parse_hosts_csv "$csv" 2>/dev/null || true)
        if [ "$#" -ne 3 ]; then
            echo "strict: invalid DS4_RING_HOSTS/--hosts (expected h0,h1,h2): $csv" >&2
            fail=1
        else
            if ! hosts_unique "$1" "$2" "$3"; then
                echo "strict: DS4_RING_HOSTS entries must be unique: $csv" >&2
                fail=1
            else
                h0="$1"
                h1="$2"
                h2="$3"
            fi
        fi
    fi

    if [ "$h0" != "" ] && [ "${DS4_MASTER_ADDR:-}" != "" ]; then
        master="${DS4_MASTER_ADDR:-}"
        if [ "$master" != "$h0" ]; then
            h0_ip="$(resolve_ipv4_best_effort "$h0" 2>/dev/null || true)"
            master_ip="$(resolve_ipv4_best_effort "$master" 2>/dev/null || true)"
            if [ "$h0_ip" != "" ] && [ "$master_ip" != "" ] && [ "$h0_ip" != "$master_ip" ]; then
                echo "strict: DS4_MASTER_ADDR does not match ring rank0 host (ring[0]=$h0, master=$master)" >&2
                echo "strict: ring[0] ipv4=$h0_ip master ipv4=$master_ip" >&2
                fail=1
            fi
        fi
    fi

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

    if [ "$fail" -ne 0 ]; then
        return 1
    fi
    return 0
}

parse_hosts_csv()
{
    csv="$1"
    h0=""
    h1=""
    h2=""

    if [ "$csv" = "" ]; then
        return 1
    fi

    h0="$(trim_ws "${csv%%,*}")"
    rest="${csv#*,}"
    if [ "$rest" = "$csv" ]; then
        return 1
    fi
    h1="$(trim_ws "${rest%%,*}")"
    rest="${rest#*,}"
    if [ "$rest" = "$h1" ]; then
        return 1
    fi
    h2="$(trim_ws "$rest")"

    case "$h2" in
        *,*)
            return 1
            ;;
    esac

    if [ "$h0" = "" ] || [ "$h1" = "" ] || [ "$h2" = "" ]; then
        return 1
    fi

    echo "$h0" "$h1" "$h2"
    return 0
}

self_host_from_rank()
{
    h0="$1"
    h1="$2"
    h2="$3"
    r="${DS4_RANK:-}"
    if ! is_uint "$r"; then
        return 1
    fi
    case "$r" in
        0) echo "$h0"; return 0 ;;
        1) echo "$h1"; return 0 ;;
        2) echo "$h2"; return 0 ;;
    esac
    return 1
}

ring_neighbors()
{
    h0="$1"
    h1="$2"
    h2="$3"
    r="${DS4_RANK:-}"
    if ! is_uint "$r"; then
        return 1
    fi
    case "$r" in
        0)
            echo "$h2" "$h1"
            return 0
            ;;
        1)
            echo "$h0" "$h2"
            return 0
            ;;
        2)
            echo "$h1" "$h0"
            return 0
            ;;
    esac
    return 1
}

peer_master_backcheck_best_effort()
{
    peer_ssh="${DS4_PEER_SSH:-}"
    peer_host="${DS4_PEER_HOST:-}"

    if [ "$peer_ssh" = "" ]; then
        echo "peer ssh: skip (DS4_PEER_SSH unset)"
        return 0
    fi
    if [ "$peer_host" = "" ]; then
        echo "peer ssh: skip (DS4_PEER_HOST unset; needed for peer reachability context)"
        return 0
    fi
    if [ "${DS4_MASTER_ADDR:-}" = "" ] || [ "${DS4_MASTER_PORT:-}" = "" ]; then
        echo "peer ssh: skip (DS4_MASTER_ADDR/DS4_MASTER_PORT unset)"
        return 0
    fi

    echo "== peer -> master backcheck via ssh ($peer_ssh) (best effort) =="
    ssh $SSH_OPTS "$peer_ssh" sh -c '
set -eu
peer_host="${1:-}"
master_addr="${2:-}"
master_port="${3:-}"
metrics_port="${4:-}"
echo "peer_host=${peer_host}"
echo "master_addr=${master_addr}"
echo "master_port=${master_port}"
echo "metrics_port=${metrics_port}"
ping -c 2 "$master_addr" 2>/dev/null && echo ping_ok || echo ping_failed
if command -v nc >/dev/null 2>&1; then
	if nc -z -w 2 "$master_addr" "$master_port" 2>/dev/null; then
		echo "tcp_ok ${master_addr}:${master_port}"
	else
		echo "tcp_failed ${master_addr}:${master_port}"
	fi
else
	echo "nc_missing; skip tcp"
fi
if [ "$metrics_port" != "" ] && command -v curl >/dev/null 2>&1; then
	if curl -fsS --max-time 2 "http://${master_addr}:${metrics_port}/metrics" >/dev/null 2>&1; then
		echo "metrics_ok http://${master_addr}:${metrics_port}/metrics"
	else
		echo "metrics_failed http://${master_addr}:${metrics_port}/metrics"
	fi
else
	echo "metrics_skip"
fi
' sh "$peer_host" "$DS4_MASTER_ADDR" "$DS4_MASTER_PORT" "${DS4_METRICS_PORT:-}" || true
    echo
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

echo "== tp3 readiness (safe) =="
date -Is 2>/dev/null || date || true
echo "self=$self"
echo "topology=$topology"
echo

echo "== ds4 env (optional) =="
print_if_set DS4_INSTANCE
if [ "${DS4_INSTANCE:-}" != "" ] && [ "$self" != "$DS4_INSTANCE" ]; then
    echo "warning: DS4_INSTANCE mismatch: DS4_INSTANCE=$DS4_INSTANCE --self=$self" >&2
fi
print_if_set DS4_WORLD_SIZE
print_if_set DS4_RANK
print_if_set DS4_MASTER_ADDR
print_if_set DS4_MASTER_PORT
print_if_set DS4_METRICS_ADDR
print_if_set DS4_METRICS_PORT
print_if_set DS4_CONFIG_PATH
print_if_set DS4_EXPERT_OWNER_TABLE_PATH
print_if_set DS4_EXPERT_MANIFEST_PATH
print_if_set DS4_RING_HOSTS
print_if_set DS4_PEER_HOST
print_if_set DS4_PEER_SSH
print_if_set DS4_EXPECT_IFACE

if [ "$strict" -ne 0 ]; then
    if ! strict_validate; then
        echo "== FAIL ==" >&2
        exit 2
    fi
fi

if [ "${DS4_MASTER_ADDR:-}" != "" ]; then
    print_host_resolution "master" "$DS4_MASTER_ADDR"
    check_expected_iface "master" "$DS4_MASTER_ADDR" || exit 2
    tcp_probe_best_effort "master" "$DS4_MASTER_ADDR"
fi

if [ "${DS4_METRICS_PORT:-}" != "" ]; then
    check_metrics_endpoint "${DS4_METRICS_ADDR:-}" "${DS4_METRICS_PORT:-}"
fi

if [ "$hosts_csv" = "" ]; then
    hosts_csv="${DS4_RING_HOSTS:-}"
fi

if [ "$hosts_csv" = "" ]; then
    echo "ring hosts: skip (no --hosts and DS4_RING_HOSTS unset)"
else
    set -- $(parse_hosts_csv "$hosts_csv" 2>/dev/null || true)
    if [ "$#" -ne 3 ]; then
        echo "ring hosts: invalid csv (expected h0,h1,h2): $hosts_csv" >&2
        if [ "$strict" -ne 0 ]; then
            exit 2
        fi
    else
        h0="$1"
        h1="$2"
        h2="$3"

        echo "ring hosts: h0=$h0 h1=$h1 h2=$h2"

        peers=""
        if [ "$topology" = "ring" ]; then
            set -- $(ring_neighbors "$h0" "$h1" "$h2" 2>/dev/null || true)
            if [ "$#" -ne 2 ]; then
                echo "ring peers: skip (DS4_RANK missing/invalid?)" >&2
                if [ "$strict" -ne 0 ]; then
                    exit 2
                fi
            else
                peers="$1 $2"
            fi
        else
            self_host="$(self_host_from_rank "$h0" "$h1" "$h2" 2>/dev/null || true)"
            for h in "$h0" "$h1" "$h2"; do
                if [ "$self_host" != "" ] && [ "$h" = "$self_host" ]; then
                    continue
                fi
                peers="$peers $h"
            done
        fi

        for peer in $peers; do
            if [ "$peer" = "" ]; then
                continue
            fi
            echo "== peer ($peer) =="
            print_host_resolution "peer" "$peer"
            check_expected_iface "peer" "$peer" || exit 2
            if command -v ping >/dev/null 2>&1; then
                ping -c 2 "$peer" 2>/dev/null && echo "peer ping: ok" || echo "peer ping: failed"
            else
                echo "peer ping: ping missing; skip"
            fi
            tcp_probe_best_effort "peer" "$peer"
            check_peer_metrics_endpoint "peer" "$peer" "${DS4_METRICS_PORT:-}"
            echo
        done
    fi
fi

peer_master_backcheck_best_effort

echo "== OK =="
