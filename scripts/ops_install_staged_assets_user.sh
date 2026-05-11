#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_install_staged_assets_user.sh -- install /tmp-staged DS4 user-service assets (human-run, no sudo)

Usage:
  ops_install_staged_assets_user.sh --instance <name> [--dry-run] [--overwrite-config] [--install-spark-units] [--start-preflight] [--strict]

Environment (optional overrides):
  DS4_STAGED_SYSTEMD_USER_DIR  Default: /tmp/ds4-systemd-user
  DS4_STAGED_CONFIG_DIR        Default: /tmp/ds4-config
  DS4_STAGED_SCRIPTS_DIR       Default: /tmp/ds4-scripts

  DS4_USER_SYSTEMD_DIR         Default: $HOME/.config/systemd/user
  DS4_USER_CONFIG_DIR          Default: $HOME/.config/ds4
  DS4_USER_DS4_DIR             Default: $HOME/ds4

Notes:
  - Intended to run on a Spark after staging via scripts/ops_stage_deploy_assets.sh (Mac-side).
  - Installs systemd user-unit templates, ~/.config/ds4 env+config files, and required ops scripts.
  - Does not modify system services, networking, or host policy (e.g. lingering); see docs for those steps.
EOF
}

instance=""
dry_run=0
overwrite_config=0
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

    need_file "$src"
    if [ -f "$dst" ] && [ "$overwrite_config" -eq 0 ]; then
        echo "skip existing: $dst"
        return 0
    fi
    run install -m "$mode" "$src" "$dst"
    return 0
}

staged_systemd_user_dir="${DS4_STAGED_SYSTEMD_USER_DIR:-/tmp/ds4-systemd-user}"
staged_config_dir="${DS4_STAGED_CONFIG_DIR:-/tmp/ds4-config}"
staged_scripts_dir="${DS4_STAGED_SCRIPTS_DIR:-/tmp/ds4-scripts}"

user_systemd_dir="${DS4_USER_SYSTEMD_DIR:-$HOME/.config/systemd/user}"
user_config_dir="${DS4_USER_CONFIG_DIR:-$HOME/.config/ds4}"
user_ds4_dir="${DS4_USER_DS4_DIR:-$HOME/ds4}"
user_scripts_dir="$user_ds4_dir/scripts"

echo "== install staged ds4 user assets =="
date -Is 2>/dev/null || date || true
echo "instance=$instance"
echo "staged_systemd_user_dir=$staged_systemd_user_dir"
echo "staged_config_dir=$staged_config_dir"
echo "staged_scripts_dir=$staged_scripts_dir"
echo "user_systemd_dir=$user_systemd_dir"
echo "user_config_dir=$user_config_dir"
echo "user_ds4_dir=$user_ds4_dir"
echo

echo "== sanity check: expected DS4 checkout layout =="
if [ ! -d "$user_ds4_dir" ]; then
    cat <<EOF >&2
missing: $user_ds4_dir

The systemd user-unit templates in this repo expect DS4 at:
  \$HOME/ds4

If you are using a different path, either:
  - create a symlink: ln -s <your-path> "$user_ds4_dir"
  - or edit the installed templates under: $user_systemd_dir
EOF
    exit 2
fi
if [ ! -x "$user_ds4_dir/bin/ds4_server" ]; then
    echo "warning: missing executable: $user_ds4_dir/bin/ds4_server (build DS4 before starting ds4@.service)" >&2
fi
echo

echo "== systemd --user unit templates =="
need_file "$staged_systemd_user_dir/ds4@.service"
need_file "$staged_systemd_user_dir/ds4-strict@.service"
need_file "$staged_systemd_user_dir/ds4-tp3-strict@.service"
need_file "$staged_systemd_user_dir/ds4-tp4-strict@.service"
need_file "$staged_systemd_user_dir/ds4-preflight@.service"
need_file "$staged_systemd_user_dir/ds4-preflight-strict@.service"
need_file "$staged_systemd_user_dir/ds4-preflight-tp3@.service"
need_file "$staged_systemd_user_dir/ds4-preflight-tp3-strict@.service"
need_file "$staged_systemd_user_dir/ds4-preflight-tp4@.service"
need_file "$staged_systemd_user_dir/ds4-preflight-tp4-strict@.service"

run install -d -m 0755 "$user_systemd_dir"
run install -m 0644 "$staged_systemd_user_dir"/ds4*.service "$user_systemd_dir"/
echo

if [ "$install_spark_units" -ne 0 ]; then
    echo "== optional: Spark standalone user units =="
    need_file "$staged_systemd_user_dir/spark-master@.service"
    need_file "$staged_systemd_user_dir/spark-worker@.service"
    run install -m 0644 "$staged_systemd_user_dir"/spark-*.service "$user_systemd_dir"/
    if [ -f "$staged_config_dir/spark-${instance}.env.example" ]; then
        copy_if_missing "$staged_config_dir/spark-${instance}.env.example" "$user_config_dir/spark-${instance}.env" 0640
    else
        echo "warning: missing staged spark env example: $staged_config_dir/spark-${instance}.env.example" >&2
    fi
    echo
fi

echo "== ~/.config/ds4 configs (idempotent by default) =="
run install -d -m 0755 "$user_config_dir"
if [ -f "$staged_config_dir/ds4.env.example" ]; then
    copy_if_missing "$staged_config_dir/ds4.env.example" "$user_config_dir/ds4.env" 0640
fi
copy_if_missing "$staged_config_dir/ds4-${instance}.env.example" "$user_config_dir/ds4-${instance}.env" 0640
copy_if_missing "$staged_config_dir/ds4-${instance}.conf.example" "$user_config_dir/ds4-${instance}.conf" 0640
echo

echo "== required ops scripts (for ExecStartPre + preflight) =="
need_file "$staged_scripts_dir/ops_ds4_env_check.sh"
need_file "$staged_scripts_dir/ops_tp2_readiness.sh"
need_file "$staged_scripts_dir/ops_tp3_readiness.sh"
need_file "$staged_scripts_dir/ops_tp4_readiness.sh"
run install -d -m 0755 "$user_scripts_dir"
run install -m 0755 "$staged_scripts_dir/ops_ds4_env_check.sh" "$user_scripts_dir/ops_ds4_env_check.sh"
run install -m 0755 "$staged_scripts_dir/ops_tp2_readiness.sh" "$user_scripts_dir/ops_tp2_readiness.sh"
run install -m 0755 "$staged_scripts_dir/ops_tp3_readiness.sh" "$user_scripts_dir/ops_tp3_readiness.sh"
run install -m 0755 "$staged_scripts_dir/ops_tp4_readiness.sh" "$user_scripts_dir/ops_tp4_readiness.sh"
if [ "$install_spark_units" -ne 0 ] && [ -f "$staged_scripts_dir/ops_spark_standalone_check.sh" ]; then
    run install -m 0755 "$staged_scripts_dir/ops_spark_standalone_check.sh" "$user_scripts_dir/ops_spark_standalone_check.sh"
fi
if [ -f "$staged_scripts_dir/ops_collect_support_bundle.sh" ]; then
    run install -m 0755 "$staged_scripts_dir/ops_collect_support_bundle.sh" "$user_scripts_dir/ops_collect_support_bundle.sh"
fi
echo

echo "== systemctl --user daemon-reload =="
if command -v systemctl >/dev/null 2>&1; then
    run systemctl --user daemon-reload
else
    echo "skip (missing: systemctl)"
fi
echo

if [ "$start_preflight" -ne 0 ]; then
    echo "== optional: run preflight (human-run) =="
    if command -v systemctl >/dev/null 2>&1; then
        if [ "$strict" -ne 0 ]; then
            run systemctl --user start "ds4-preflight-strict@${instance}.service"
        else
            run systemctl --user start "ds4-preflight@${instance}.service"
        fi
    else
        echo "skip (missing: systemctl)"
    fi
    echo
fi

cat <<EOF

== next steps (human-run) ==
systemctl --user enable --now ds4@${instance}.service

== logs (human-run) ==
journalctl --user -u ds4@${instance}.service -n 200 --no-pager
EOF
