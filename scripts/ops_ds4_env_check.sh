#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_ds4_env_check.sh -- safe DS4 env sanity checks

Usage:
  ops_ds4_env_check.sh <path-to-ds4-*.env>

Notes:
  - Non-destructive; does not require sudo.
  - Parses env files as simple KEY=VALUE assignments (no shell execution).
  - If DS4_INSTANCE is missing, it may be inferred from a filename like:
      /etc/ds4/ds4-spark0.env  -> DS4_INSTANCE=spark0
EOF
}

env_path="${1:-}"
if [ "$env_path" = "" ]; then
    usage >&2
    exit 2
fi

if [ ! -f "$env_path" ]; then
    echo "missing env file: $env_path" >&2
    exit 2
fi
if [ ! -r "$env_path" ]; then
    echo "unreadable env file (check owner/group/mode): $env_path" >&2
    exit 2
fi

load_env_file()
{
    path="$1"
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
    done < "$path"
}

load_env_file "$env_path"

err=0

infer_instance_from_path()
{
    base="${1##*/}"
    case "$base" in
        ds4-*.env)
            inst="${base#ds4-}"
            inst="${inst%.env}"
            if [ "$inst" != "" ]; then
                echo "$inst"
                return 0
            fi
            ;;
    esac
    return 1
}

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

echo "== ds4 env check =="
echo "env: $env_path"

if [ "${DS4_INSTANCE:-}" = "" ]; then
    inferred="$(infer_instance_from_path "$env_path" 2>/dev/null || true)"
    if [ "$inferred" != "" ]; then
        DS4_INSTANCE="$inferred"
        export DS4_INSTANCE
        echo "inferred: DS4_INSTANCE=$DS4_INSTANCE"
    fi
fi

need_nonempty DS4_INSTANCE
need_nonempty DS4_HOME
need_nonempty DS4_STATE_DIR
need_nonempty DS4_LOG_DIR
need_nonempty DS4_LOG_LEVEL
need_nonempty DS4_LOG_FORMAT
need_nonempty DS4_METRICS_ADDR
need_uint DS4_METRICS_PORT
need_nonempty DS4_CONFIG_PATH

need_uint DS4_WORLD_SIZE
need_uint DS4_RANK
need_nonempty DS4_MASTER_ADDR
need_uint DS4_MASTER_PORT

if [ "${DS4_WORLD_SIZE:-0}" = "1" ]; then
    if [ "${DS4_RANK:-0}" != "0" ]; then
        echo "invalid: DS4_WORLD_SIZE=1 requires DS4_RANK=0" >&2
        err=1
    fi
fi

if [ "${DS4_WORLD_SIZE:-0}" != "1" ]; then
    if [ "${DS4_INSTANCE:-}" = "spark0" ] && [ "${DS4_RANK:-}" != "0" ]; then
        echo "invalid: spark0 should use DS4_RANK=0 for TP=2" >&2
        err=1
    fi
    if [ "${DS4_INSTANCE:-}" = "spark1" ] && [ "${DS4_RANK:-}" != "1" ]; then
        echo "invalid: spark1 should use DS4_RANK=1 for TP=2" >&2
        err=1
    fi
fi

if [ "$err" -ne 0 ]; then
    echo "== FAIL ==" >&2
    exit 2
fi

echo "== OK =="
