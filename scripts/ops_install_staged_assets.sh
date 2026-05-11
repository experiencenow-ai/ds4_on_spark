#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_install_staged_assets.sh -- install /tmp-staged DS4 deploy assets (human-run)

Usage:
  ops_install_staged_assets.sh --instance <name> [--dry-run] [--overwrite-config] [--install-timers] [--install-spark-units] [--start-preflight] [--strict]

Environment (optional overrides):
  DS4_STAGED_SYSTEMD_DIR   Default: /tmp/ds4-systemd
  DS4_STAGED_CONFIG_DIR    Default: /tmp/ds4-config
  DS4_STAGED_SYSUSERS_DIR  Default: /tmp/ds4-sysusers
  DS4_STAGED_TMPFILES_DIR  Default: /tmp/ds4-tmpfiles
  DS4_STAGED_SCRIPTS_DIR   Default: /tmp/ds4-scripts

Notes:
  - Intended to run on a Spark after staging via scripts/ops_stage_deploy_assets.sh.
  - Requires root privileges to write under /etc and /opt; run with sudo.
  - Does not modify networking; installs files and reloads systemd.
  - By default, does not overwrite existing /etc/ds4/ds4-*.env or ds4-*.conf.
  - Timer templates are optional and installed only with --install-timers.
EOF
}

instance=""
dry_run=0
overwrite_config=0
install_timers=0
install_spark_units=0
start_preflight=0
strict=0

while [ $# -gt 0 ]; do
    case "$1" in
        --instance)
            instance="${2:-}"
            shift 2
            ;;
        --dry-run)
            dry_run=1
            shift
            ;;
        --overwrite-config)
            overwrite_config=1
            shift
            ;;
        --install-timers)
            install_timers=1
            shift
            ;;
        --install-spark-units)
            install_spark_units=1
            shift
            ;;
        --start-preflight)
            start_preflight=1
            shift
            ;;
        --strict)
            strict=1
            shift
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

run()
{
    if [ "$dry_run" -ne 0 ]; then
        echo "+ $*"
        return 0
    fi
    echo "+ $*"
    "$@"
}

need_file()
{
    path="$1"
    if [ ! -f "$path" ]; then
        echo "missing: $path" >&2
        exit 2
    fi
}

copy_if_missing()
{
    src="$1"
    dst="$2"
    mode="$3"
    group="$4"

    need_file "$src"
    if [ -f "$dst" ] && [ "$overwrite_config" -eq 0 ]; then
        echo "skip existing: $dst"
        return 0
    fi
    if [ "$group" != "" ]; then
        run install -g "$group" -m "$mode" "$src" "$dst"
    else
        run install -m "$mode" "$src" "$dst"
    fi
    return 0
}

staged_systemd_dir="${DS4_STAGED_SYSTEMD_DIR:-/tmp/ds4-systemd}"
staged_config_dir="${DS4_STAGED_CONFIG_DIR:-/tmp/ds4-config}"
staged_sysusers_dir="${DS4_STAGED_SYSUSERS_DIR:-/tmp/ds4-sysusers}"
staged_tmpfiles_dir="${DS4_STAGED_TMPFILES_DIR:-/tmp/ds4-tmpfiles}"
staged_scripts_dir="${DS4_STAGED_SCRIPTS_DIR:-/tmp/ds4-scripts}"

systemd_dir="/etc/systemd/system"
config_dir="/etc/ds4"
scripts_dir="/opt/ds4/scripts"

echo "== install staged ds4 assets =="
date -Is 2>/dev/null || date || true
echo "instance=$instance"
echo "staged_systemd_dir=$staged_systemd_dir"
echo "staged_config_dir=$staged_config_dir"
echo "staged_sysusers_dir=$staged_sysusers_dir"
echo "staged_tmpfiles_dir=$staged_tmpfiles_dir"
echo "staged_scripts_dir=$staged_scripts_dir"
echo

if [ "$dry_run" -eq 0 ]; then
    if [ "$(id -u)" -ne 0 ]; then
        echo "must run as root (use: sudo $0 --instance $instance ...)" >&2
        exit 2
    fi
fi

ds4_group=""
if command -v getent >/dev/null 2>&1; then
    if getent group ds4 >/dev/null 2>&1; then
        ds4_group="ds4"
    fi
fi

echo "== optional: validate staged assets =="
if [ -x "$staged_scripts_dir/ops_validate_staged_assets.sh" ]; then
    run "$staged_scripts_dir/ops_validate_staged_assets.sh"
else
    echo "skip (missing: $staged_scripts_dir/ops_validate_staged_assets.sh)"
fi
echo

echo "== sysusers/tmpfiles (optional, human-run) =="
need_file "$staged_sysusers_dir/ds4.conf"
need_file "$staged_tmpfiles_dir/ds4.conf"
run install -d -m 0755 /etc/sysusers.d /etc/tmpfiles.d
run install -m 0644 "$staged_sysusers_dir/ds4.conf" /etc/sysusers.d/ds4.conf
run install -m 0644 "$staged_tmpfiles_dir/ds4.conf" /etc/tmpfiles.d/ds4.conf
if command -v systemd-sysusers >/dev/null 2>&1; then
    run systemd-sysusers || true
else
    echo "skip systemd-sysusers (missing)"
fi
if command -v systemd-tmpfiles >/dev/null 2>&1; then
    run systemd-tmpfiles --create || true
else
    echo "skip systemd-tmpfiles (missing)"
fi
echo

echo "== systemd unit templates =="
need_file "$staged_systemd_dir/ds4@.service"
need_file "$staged_systemd_dir/ds4-strict@.service"
need_file "$staged_systemd_dir/ds4-preflight@.service"
need_file "$staged_systemd_dir/ds4-preflight-strict@.service"
need_file "$staged_systemd_dir/ds4-support-bundle@.service"

run install -m 0644 "$staged_systemd_dir"/ds4*.service "$systemd_dir"/
if [ "$install_timers" -ne 0 ]; then
    run install -m 0644 "$staged_systemd_dir"/ds4*.timer "$systemd_dir"/
else
    echo "skip timers (use --install-timers)"
fi

if [ "$install_spark_units" -ne 0 ]; then
    if ls "$staged_systemd_dir"/spark-*.service >/dev/null 2>&1; then
        run install -m 0644 "$staged_systemd_dir"/spark-*.service "$systemd_dir"/
    else
        echo "skip spark units (none staged)"
    fi
else
    echo "skip spark units (use --install-spark-units)"
fi
echo

echo "== /etc/ds4 configs (idempotent by default) =="
if [ "$ds4_group" != "" ]; then
    run install -d -g "$ds4_group" -m 0750 "$config_dir"
else
    run install -d -m 0755 "$config_dir"
fi

copy_if_missing "$staged_config_dir/ds4-${instance}.env.example" "$config_dir/ds4-${instance}.env" 0640 "$ds4_group"
copy_if_missing "$staged_config_dir/ds4-${instance}.conf.example" "$config_dir/ds4-${instance}.conf" 0640 "$ds4_group"
if [ ! -f "$config_dir/ds4.env" ]; then
    if [ -f "$staged_config_dir/ds4.env.example" ]; then
        copy_if_missing "$staged_config_dir/ds4.env.example" "$config_dir/ds4.env" 0640 "$ds4_group"
    fi
fi

if [ "$install_spark_units" -ne 0 ]; then
    if [ -f "$staged_config_dir/spark-${instance}.env.example" ]; then
        copy_if_missing "$staged_config_dir/spark-${instance}.env.example" "$config_dir/spark-${instance}.env" 0640 "$ds4_group"
    else
        echo "skip spark env (missing staged example: $staged_config_dir/spark-${instance}.env.example)"
    fi
fi
echo

echo "== /opt/ds4 scripts =="
run install -d -m 0755 /opt/ds4 "$scripts_dir"
	need_file "$staged_scripts_dir/ops_tp2_readiness.sh"
	need_file "$staged_scripts_dir/ops_tp4_readiness.sh"
	need_file "$staged_scripts_dir/ops_ds4_env_check.sh"
	need_file "$staged_scripts_dir/ops_ds4_config_check.sh"
	need_file "$staged_scripts_dir/ops_collect_support_bundle.sh"
	run install -m 0755 "$staged_scripts_dir/ops_tp2_readiness.sh" "$scripts_dir/ops_tp2_readiness.sh"
	run install -m 0755 "$staged_scripts_dir/ops_tp4_readiness.sh" "$scripts_dir/ops_tp4_readiness.sh"
	run install -m 0755 "$staged_scripts_dir/ops_ds4_env_check.sh" "$scripts_dir/ops_ds4_env_check.sh"
	run install -m 0755 "$staged_scripts_dir/ops_ds4_config_check.sh" "$scripts_dir/ops_ds4_config_check.sh"
	run install -m 0755 "$staged_scripts_dir/ops_collect_support_bundle.sh" "$scripts_dir/ops_collect_support_bundle.sh"
if [ -f "$staged_scripts_dir/ops_validate_installed_assets.sh" ]; then
    run install -m 0755 "$staged_scripts_dir/ops_validate_installed_assets.sh" "$scripts_dir/ops_validate_installed_assets.sh"
fi
if [ -f "$staged_scripts_dir/ops_validate_staged_assets.sh" ]; then
    run install -m 0755 "$staged_scripts_dir/ops_validate_staged_assets.sh" "$scripts_dir/ops_validate_staged_assets.sh"
fi
echo

echo "== systemd reload =="
if command -v systemctl >/dev/null 2>&1; then
    run systemctl daemon-reload
else
    echo "skip systemctl daemon-reload (missing)"
fi
echo

if [ "$start_preflight" -ne 0 ]; then
    echo "== optional: start preflight =="
    if command -v systemctl >/dev/null 2>&1; then
        if [ "$strict" -ne 0 ]; then
            run systemctl start "ds4-preflight-strict@${instance}.service"
        else
            run systemctl start "ds4-preflight@${instance}.service"
        fi
    else
        echo "skip (systemctl missing)"
    fi
    echo
fi

echo "== done =="
