#!/usr/bin/env sh
set -eu

usage()
{
    cat <<'EOF'
ops_validate_staged_assets.sh -- validate /tmp-staged DS4 deploy assets (safe)

Usage:
  ops_validate_staged_assets.sh

Environment (optional overrides):
  DS4_STAGED_SYSTEMD_DIR   Default: /tmp/ds4-systemd
  DS4_STAGED_CONFIG_DIR    Default: /tmp/ds4-config
  DS4_STAGED_SYSUSERS_DIR  Default: /tmp/ds4-sysusers
  DS4_STAGED_TMPFILES_DIR  Default: /tmp/ds4-tmpfiles
  DS4_STAGED_SCRIPTS_DIR   Default: /tmp/ds4-scripts

Notes:
  - Non-destructive; does not require sudo.
  - Intended to run on a Spark after staging via scripts/ops_stage_deploy_assets.sh.
  - Performs lightweight consistency checks:
    - required staged template/example files exist
    - staged ops scripts pass `sh -n`
    - staged env examples include required keys expected by ops_ds4_env_check.sh
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi
if [ "${1:-}" != "" ]; then
    echo "unexpected arg: $1" >&2
    usage >&2
    exit 2
fi

systemd_dir="${DS4_STAGED_SYSTEMD_DIR:-/tmp/ds4-systemd}"
config_dir="${DS4_STAGED_CONFIG_DIR:-/tmp/ds4-config}"
sysusers_dir="${DS4_STAGED_SYSUSERS_DIR:-/tmp/ds4-sysusers}"
tmpfiles_dir="${DS4_STAGED_TMPFILES_DIR:-/tmp/ds4-tmpfiles}"
scripts_dir="${DS4_STAGED_SCRIPTS_DIR:-/tmp/ds4-scripts}"

need_file()
{
    path="$1"
    if [ ! -f "$path" ]; then
        echo "missing: $path" >&2
        exit 2
    fi
}

need_key_in_file()
{
    key="$1"
    path="$2"
    if ! grep -E "^[[:space:]]*${key}=" "$path" >/dev/null 2>&1; then
        echo "missing key in $path: $key" >&2
        exit 2
    fi
}

echo "== validate staged ds4 assets =="
echo "systemd_dir=$systemd_dir"
echo "config_dir=$config_dir"
echo "sysusers_dir=$sysusers_dir"
echo "tmpfiles_dir=$tmpfiles_dir"
echo "scripts_dir=$scripts_dir"

need_file "$sysusers_dir/ds4.conf"
need_file "$tmpfiles_dir/ds4.conf"

need_file "$systemd_dir/ds4@.service"
need_file "$systemd_dir/ds4-strict@.service"
need_file "$systemd_dir/ds4-preflight@.service"
need_file "$systemd_dir/ds4-preflight-strict@.service"
need_file "$systemd_dir/ds4-support-bundle@.service"
need_file "$systemd_dir/ds4-preflight@.timer"
need_file "$systemd_dir/ds4-preflight-strict@.timer"
need_file "$systemd_dir/ds4-support-bundle@.timer"

need_file "$config_dir/ds4.env.example"
need_file "$config_dir/ds4-spark0.env.example"
need_file "$config_dir/ds4-spark1.env.example"
need_file "$config_dir/ds4-spark0.conf.example"
need_file "$config_dir/ds4-spark1.conf.example"
need_file "$config_dir/journald.ds4.conf.example"
need_file "$config_dir/logrotate.ds4.conf.example"
need_file "$config_dir/prometheus-scrape.ds4.yml.example"
need_file "$config_dir/hosts.ds4.spark01.example"
need_file "$config_dir/ssh_config.ds4.spark01.example"
need_file "$config_dir/sysctl.ds4.conf.example"

need_file "$scripts_dir/ops_ds4_env_check.sh"
need_file "$scripts_dir/ops_tp2_readiness.sh"
need_file "$scripts_dir/ops_spark_standalone_check.sh"
need_file "$scripts_dir/ops_collect_support_bundle.sh"
need_file "$scripts_dir/ops_validate_staged_assets.sh"
need_file "$scripts_dir/ops_validate_installed_assets.sh"
need_file "$scripts_dir/ops_install_staged_assets.sh"

echo "== sh -n (staged ops scripts) =="
sh -n "$scripts_dir/ops_ds4_env_check.sh"
sh -n "$scripts_dir/ops_tp2_readiness.sh"
sh -n "$scripts_dir/ops_spark_standalone_check.sh"
sh -n "$scripts_dir/ops_collect_support_bundle.sh"
sh -n "$scripts_dir/ops_validate_staged_assets.sh"
sh -n "$scripts_dir/ops_validate_installed_assets.sh"
sh -n "$scripts_dir/ops_install_staged_assets.sh"

echo "== env examples include required keys =="
for env in "$config_dir/ds4.env.example" "$config_dir/ds4-spark0.env.example" "$config_dir/ds4-spark1.env.example"; do
    need_key_in_file "DS4_INSTANCE" "$env"
    need_key_in_file "DS4_HOME" "$env"
    need_key_in_file "DS4_STATE_DIR" "$env"
    need_key_in_file "DS4_LOG_DIR" "$env"
    need_key_in_file "DS4_LOG_LEVEL" "$env"
    need_key_in_file "DS4_LOG_FORMAT" "$env"
    need_key_in_file "DS4_METRICS_ADDR" "$env"
    need_key_in_file "DS4_METRICS_PORT" "$env"
    need_key_in_file "DS4_CONFIG_PATH" "$env"
    need_key_in_file "DS4_WORLD_SIZE" "$env"
    need_key_in_file "DS4_RANK" "$env"
    need_key_in_file "DS4_MASTER_ADDR" "$env"
    need_key_in_file "DS4_MASTER_PORT" "$env"
done

echo "== ok =="
