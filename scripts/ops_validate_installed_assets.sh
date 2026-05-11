#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_validate_installed_assets.sh -- validate installed DS4 assets (safe)

Usage:
  ops_validate_installed_assets.sh --instance <name> [--strict]

Options:
  --systemd-dir <path>   Default: /etc/systemd/system
  --config-dir <path>    Default: /etc/ds4
  --scripts-dir <path>   Default: /opt/ds4/scripts

Notes:
  - Non-destructive; does not require sudo.
  - Intended to run on a Spark after installing templates under /etc and scripts under /opt.
  - Validates installed unit templates + env/config readability, then runs:
      - ops_ds4_env_check.sh (env sanity)
      - ops_tp2_readiness.sh (preflight; add --strict to fail fast) when DS4_WORLD_SIZE != 4
      - ops_tp3_readiness.sh (preflight; add --strict to fail fast) when DS4_WORLD_SIZE == 3 and the script is installed
      - ops_tp4_readiness.sh (preflight; add --strict to fail fast) when DS4_WORLD_SIZE == 4 and the script is installed
  - systemd timer templates are optional; this script does not require them.
EOF
}

instance=""
strict=0
systemd_dir="/etc/systemd/system"
config_dir="/etc/ds4"
scripts_dir="/opt/ds4/scripts"

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

echo "== validate installed ds4 assets =="
date -Is 2>/dev/null || date || true
echo "instance=$instance"
echo "systemd_dir=$systemd_dir"
echo "config_dir=$config_dir"
echo "scripts_dir=$scripts_dir"
echo

echo "== systemd templates =="
need_file "$systemd_dir/ds4@.service"
need_file "$systemd_dir/ds4-strict@.service"
need_file "$systemd_dir/ds4-preflight@.service"
need_file "$systemd_dir/ds4-preflight-strict@.service"
need_file "$systemd_dir/ds4-support-bundle@.service"
if [ -f "$systemd_dir/ds4-preflight@.timer" ]; then
    need_file "$systemd_dir/ds4-preflight@.timer"
fi
if [ -f "$systemd_dir/ds4-preflight-strict@.timer" ]; then
    need_file "$systemd_dir/ds4-preflight-strict@.timer"
fi
if [ -f "$systemd_dir/ds4-support-bundle@.timer" ]; then
    need_file "$systemd_dir/ds4-support-bundle@.timer"
fi
echo "ok"
echo

echo "== systemd unit syntax (best effort) =="
if command -v systemd-analyze >/dev/null 2>&1; then
    units="$systemd_dir/ds4@.service $systemd_dir/ds4-strict@.service $systemd_dir/ds4-preflight@.service $systemd_dir/ds4-preflight-strict@.service $systemd_dir/ds4-support-bundle@.service"
    if [ -f "$systemd_dir/ds4-preflight@.timer" ]; then
        units="$units $systemd_dir/ds4-preflight@.timer"
    fi
    if [ -f "$systemd_dir/ds4-preflight-strict@.timer" ]; then
        units="$units $systemd_dir/ds4-preflight-strict@.timer"
    fi
    if [ -f "$systemd_dir/ds4-support-bundle@.timer" ]; then
        units="$units $systemd_dir/ds4-support-bundle@.timer"
    fi
    if systemd-analyze verify $units >/dev/null 2>&1; then
        echo "systemd-analyze verify: ok"
    else
        echo "systemd-analyze verify: reported issues (review output by re-running without redirection)" >&2
    fi
else
    echo "skip (missing: systemd-analyze)"
fi
echo

echo "== /etc/ds4 env/config =="
if [ -f "$config_dir/ds4.env" ]; then
    need_file "$config_dir/ds4.env"
fi
need_file "$config_dir/ds4-${instance}.env"
echo "ok"
echo

echo "== /opt/ds4 scripts =="
need_exec "$scripts_dir/ops_ds4_env_check.sh"
need_exec "$scripts_dir/ops_ds4_config_check.sh"
need_exec "$scripts_dir/ops_tp2_readiness.sh"
if [ -x "$scripts_dir/ops_tp3_readiness.sh" ]; then
    need_exec "$scripts_dir/ops_tp3_readiness.sh"
fi
if [ -x "$scripts_dir/ops_tp4_readiness.sh" ]; then
    need_exec "$scripts_dir/ops_tp4_readiness.sh"
fi
need_exec "$scripts_dir/ops_collect_support_bundle.sh"
echo "ok"
echo

echo "== ds4 env sanity =="
"$scripts_dir/ops_ds4_env_check.sh" "-$config_dir/ds4.env" "$config_dir/ds4-${instance}.env"
echo

world_size="$(awk -F= '/^[[:space:]]*DS4_WORLD_SIZE=/ {gsub(/[[:space:]]/,"",$2); print $2; exit}' "$config_dir/ds4-${instance}.env" 2>/dev/null || true)"
if [ "$world_size" = "4" ] && [ -x "$scripts_dir/ops_tp4_readiness.sh" ]; then
    echo "== ds4 tp=4 preflight =="
    if [ "$strict" -ne 0 ]; then
        "$scripts_dir/ops_tp4_readiness.sh" --strict --self "$instance" --topology ring --env "-$config_dir/ds4.env" --env "$config_dir/ds4-${instance}.env"
    else
        "$scripts_dir/ops_tp4_readiness.sh" --self "$instance" --topology ring --env "-$config_dir/ds4.env" --env "$config_dir/ds4-${instance}.env"
    fi
elif [ "$world_size" = "3" ] && [ -x "$scripts_dir/ops_tp3_readiness.sh" ]; then
    echo "== ds4 tp=3 preflight =="
    if [ "$strict" -ne 0 ]; then
        "$scripts_dir/ops_tp3_readiness.sh" --strict --self "$instance" --topology ring --env "-$config_dir/ds4.env" --env "$config_dir/ds4-${instance}.env"
    else
        "$scripts_dir/ops_tp3_readiness.sh" --self "$instance" --topology ring --env "-$config_dir/ds4.env" --env "$config_dir/ds4-${instance}.env"
    fi
else
    echo "== ds4 tp=2 preflight =="
    if [ "$strict" -ne 0 ]; then
        "$scripts_dir/ops_tp2_readiness.sh" --strict --self "$instance" --env "-$config_dir/ds4.env" --env "$config_dir/ds4-${instance}.env"
    else
        "$scripts_dir/ops_tp2_readiness.sh" --self "$instance" --env "-$config_dir/ds4.env" --env "$config_dir/ds4-${instance}.env"
    fi
fi
echo

echo "== ok =="
