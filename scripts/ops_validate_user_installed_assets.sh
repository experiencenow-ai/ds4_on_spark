#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_validate_user_installed_assets.sh -- validate installed DS4 user-service assets (safe)

Usage:
  ops_validate_user_installed_assets.sh --instance <name> [--strict]

Options:
  --systemd-dir <path>   Default: $HOME/.config/systemd/user
  --config-dir <path>    Default: $HOME/.config/ds4
  --scripts-dir <path>   Default: $HOME/ds4/scripts

Notes:
  - Non-destructive; does not require sudo.
  - Intended to run on a Spark after installing user-unit templates under ~/.config/systemd/user.
  - Validates installed unit templates + env/config readability, then runs:
      - ops_ds4_env_check.sh (env sanity)
      - ops_tp2_readiness.sh (preflight; add --strict to fail fast) when DS4_WORLD_SIZE != 4
      - ops_tp3_readiness.sh (preflight; add --strict to fail fast) when DS4_WORLD_SIZE == 3 and the script is installed
      - ops_tp4_readiness.sh (preflight; add --strict to fail fast) when DS4_WORLD_SIZE == 4 and the script is installed
EOF
}

instance=""
strict=0
systemd_dir="$HOME/.config/systemd/user"
config_dir="$HOME/.config/ds4"
scripts_dir="$HOME/ds4/scripts"

while [ $# -gt 0 ]; do
    case "$1" in
        --instance)
            instance="${2:-}"
            shift 2
            ;;
        --strict)
            strict=1
            shift
            ;;
        --systemd-dir)
            systemd_dir="${2:-}"
            shift 2
            ;;
        --config-dir)
            config_dir="${2:-}"
            shift 2
            ;;
        --scripts-dir)
            scripts_dir="${2:-}"
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

if [ "$instance" = "" ]; then
    echo "--instance is required" >&2
    usage >&2
    exit 2
fi

need_file()
{
    path="$1"
    if [ ! -f "$path" ]; then
        echo "missing: $path" >&2
        exit 2
    fi
    if [ ! -r "$path" ]; then
        echo "unreadable: $path" >&2
        exit 2
    fi
}

need_exec()
{
    path="$1"
    need_file "$path"
    if [ ! -x "$path" ]; then
        echo "not executable: $path" >&2
        exit 2
    fi
}

echo "== validate installed ds4 user assets =="
date -Is 2>/dev/null || date || true
echo "instance=$instance"
echo "systemd_dir=$systemd_dir"
echo "config_dir=$config_dir"
echo "scripts_dir=$scripts_dir"
echo

echo "== systemd user templates =="
need_file "$systemd_dir/ds4@.service"
need_file "$systemd_dir/ds4-strict@.service"
need_file "$systemd_dir/ds4-tp3-strict@.service"
need_file "$systemd_dir/ds4-tp4-strict@.service"
need_file "$systemd_dir/ds4-preflight@.service"
need_file "$systemd_dir/ds4-preflight-strict@.service"
need_file "$systemd_dir/ds4-preflight-tp3@.service"
need_file "$systemd_dir/ds4-preflight-tp3-strict@.service"
need_file "$systemd_dir/ds4-preflight-tp4@.service"
need_file "$systemd_dir/ds4-preflight-tp4-strict@.service"
if [ -f "$systemd_dir/spark-master@.service" ] || [ -f "$systemd_dir/spark-worker@.service" ]; then
    echo
    echo "== optional: Spark standalone user templates =="
    if [ -f "$systemd_dir/spark-master@.service" ]; then
        need_file "$systemd_dir/spark-master@.service"
    fi
    if [ -f "$systemd_dir/spark-worker@.service" ]; then
        need_file "$systemd_dir/spark-worker@.service"
    fi
    need_file "$config_dir/spark-${instance}.env"
fi
echo

echo "== ~/.config/ds4 configs =="
if [ -f "$config_dir/ds4.env" ]; then
    need_file "$config_dir/ds4.env"
fi
need_file "$config_dir/ds4-${instance}.env"
need_file "$config_dir/ds4-${instance}.conf"
echo

echo "== ops scripts =="
need_exec "$scripts_dir/ops_ds4_env_check.sh"
need_exec "$scripts_dir/ops_tp2_readiness.sh"
if [ -x "$scripts_dir/ops_tp3_readiness.sh" ]; then
    need_exec "$scripts_dir/ops_tp3_readiness.sh"
fi
if [ -x "$scripts_dir/ops_tp4_readiness.sh" ]; then
    need_exec "$scripts_dir/ops_tp4_readiness.sh"
fi
echo

echo "== env sanity =="
set -- "$scripts_dir/ops_ds4_env_check.sh"
if [ -f "$config_dir/ds4.env" ]; then
    set -- "$@" "-$config_dir/ds4.env"
fi
set -- "$@" "$config_dir/ds4-${instance}.env"
"$@"
echo

world_size="$(grep -E '^[[:space:]]*DS4_WORLD_SIZE=' "$config_dir/ds4-${instance}.env" | tail -n 1 | cut -d= -f2- | tr -d '[:space:]' 2>/dev/null || true)"
if [ "$world_size" = "" ]; then
    echo "warning: could not parse DS4_WORLD_SIZE from $config_dir/ds4-${instance}.env; defaulting to TP=2 preflight" >&2
    world_size="2"
fi

echo "== preflight =="
preflight_script="$scripts_dir/ops_tp2_readiness.sh"
if [ "$world_size" = "3" ] && [ -x "$scripts_dir/ops_tp3_readiness.sh" ]; then
    preflight_script="$scripts_dir/ops_tp3_readiness.sh"
fi
if [ "$world_size" = "4" ] && [ -x "$scripts_dir/ops_tp4_readiness.sh" ]; then
    preflight_script="$scripts_dir/ops_tp4_readiness.sh"
fi

set -- "$preflight_script" --self "$instance" --env "-$config_dir/ds4.env" --env "$config_dir/ds4-${instance}.env"
if [ ! -f "$config_dir/ds4.env" ]; then
    set -- "$preflight_script" --self "$instance" --env "$config_dir/ds4-${instance}.env"
fi
if [ "$strict" -ne 0 ]; then
    set -- "$@" --strict
fi
"$@"

echo
echo "== ok =="
