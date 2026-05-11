#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_ds4_env_check.sh -- safe DS4 env sanity checks

Usage:
  ops_ds4_env_check.sh [-/path/to/shared.env] <path-to-ds4-*.env> [more.env ...]

Notes:
  - Non-destructive; does not require sudo.
  - Parses env files as simple KEY=VALUE assignments (no shell execution).
  - If DS4_INSTANCE is missing, it may be inferred from a filename like:
      /etc/ds4/ds4-spark0.env  -> DS4_INSTANCE=spark0
  - Prefix a path with '-' to make it optional (skipped when missing), e.g.:
      ops_ds4_env_check.sh -/etc/ds4/ds4.env /etc/ds4/ds4-spark0.env
EOF
}

if [ "$#" -lt 1 ]; then
    usage >&2
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

loaded=""
infer_path=""

while [ $# -gt 0 ]; do
    raw="$1"
    shift

    optional=0
    path="$raw"
    case "$raw" in
        -/*)
            optional=1
            path="${raw#-}"
            ;;
    esac

    if [ ! -f "$path" ]; then
        if [ "$optional" -ne 0 ]; then
            continue
        fi
        echo "missing env file: $path" >&2
        exit 2
    fi
    if [ ! -r "$path" ]; then
        echo "unreadable env file (check owner/group/mode): $path" >&2
        exit 2
    fi

    load_env_file "$path"
    loaded="$loaded $path"
    case "${path##*/}" in
        ds4-*.env)
            infer_path="$path"
            ;;
    esac
done

if [ "$loaded" = "" ]; then
    echo "no env files loaded (all optional paths missing?)" >&2
    exit 2
fi

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
echo "envs:$loaded"

if [ "${DS4_INSTANCE:-}" = "" ]; then
    inferred="$(infer_instance_from_path "$infer_path" 2>/dev/null || true)"
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

if [ "${DS4_CONFIG_PATH:-}" != "" ]; then
	if [ ! -f "$DS4_CONFIG_PATH" ]; then
		echo "missing file: DS4_CONFIG_PATH=$DS4_CONFIG_PATH" >&2
		err=1
	elif [ ! -r "$DS4_CONFIG_PATH" ]; then
		echo "unreadable file: DS4_CONFIG_PATH=$DS4_CONFIG_PATH" >&2
		err=1
	else
		scripts_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
		if [ -x "$scripts_dir/ops_ds4_config_check.sh" ]; then
			if ! "$scripts_dir/ops_ds4_config_check.sh" "$DS4_CONFIG_PATH" >/dev/null 2>&1; then
				echo "invalid ds4 config: DS4_CONFIG_PATH=$DS4_CONFIG_PATH" >&2
				"$scripts_dir/ops_ds4_config_check.sh" "$DS4_CONFIG_PATH" >&2 || true
				err=1
			fi
		else
			bad_line="$(grep -n -E '^[[:space:]]*[^#[:space:]]' "$DS4_CONFIG_PATH" 2>/dev/null | grep -n -v '=' 2>/dev/null | head -n 1 || true)"
			if [ "$bad_line" != "" ]; then
				echo "invalid config syntax (expected key=value or comment): DS4_CONFIG_PATH=$DS4_CONFIG_PATH" >&2
				echo "$bad_line" >&2
				err=1
			fi
		fi
	fi
fi

need_uint DS4_WORLD_SIZE
need_uint DS4_RANK
need_nonempty DS4_MASTER_ADDR
need_uint DS4_MASTER_PORT

port_in_range()
{
    key="$1"
    eval "val=\${$key:-}"
    case "$val" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac
    if [ "$val" -lt 1 ] || [ "$val" -gt 65535 ]; then
        echo "invalid port: $key=$val (expected 1-65535)" >&2
        err=1
        return 1
    fi
    return 0
}

warn()
{
    echo "warning: $*" >&2
}

if [ "${DS4_METRICS_PORT:-}" != "" ]; then
    port_in_range DS4_METRICS_PORT || true
fi
if [ "${DS4_MASTER_PORT:-}" != "" ]; then
    port_in_range DS4_MASTER_PORT || true
fi

if [ "${DS4_WORLD_SIZE:-0}" = "1" ]; then
    if [ "${DS4_RANK:-0}" != "0" ]; then
        echo "invalid: DS4_WORLD_SIZE=1 requires DS4_RANK=0" >&2
        err=1
    fi
fi

if [ "${DS4_WORLD_SIZE:-0}" != "1" ]; then
    case "${DS4_MASTER_ADDR:-}" in
        127.0.0.1|localhost)
            warn "DS4_MASTER_ADDR=${DS4_MASTER_ADDR} looks loopback for DS4_WORLD_SIZE=${DS4_WORLD_SIZE} (verify multi-host vs single-host intent)"
            ;;
    esac
    if [ "${DS4_PEER_HOST:-}" = "" ]; then
        warn "DS4_PEER_HOST is empty (peer ping/TCP checks will be skipped)"
    fi
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
