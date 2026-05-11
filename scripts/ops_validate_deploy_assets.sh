#!/usr/bin/env sh
set -eu

usage()
{
	cat <<'EOF'
ops_validate_deploy_assets.sh -- validate deploy/ + ops scripts (safe)

Usage:
  ops_validate_deploy_assets.sh

Notes:
  - Non-destructive; intended to run from the repo root (Mac-side).
  - Performs lightweight consistency checks for deploy assets:
    - required template/example files exist
    - ops scripts pass `sh -n`
    - env examples include required keys expected by ops_ds4_env_check.sh
EOF
}

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$root"

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

echo "== validate deploy assets =="

need_file "deploy/README.md"
need_file "deploy/sysusers.d/ds4.conf"
need_file "deploy/tmpfiles.d/ds4.conf"

need_file "deploy/systemd/ds4@.service"
need_file "deploy/systemd/ds4-strict@.service"
need_file "deploy/systemd/ds4-tp3-strict@.service"
need_file "deploy/systemd/ds4-tp4-strict@.service"
need_file "deploy/systemd/ds4-preflight@.service"
need_file "deploy/systemd/ds4-preflight-strict@.service"
need_file "deploy/systemd/ds4-preflight-tp3@.service"
need_file "deploy/systemd/ds4-preflight-tp3-strict@.service"
need_file "deploy/systemd/ds4-preflight-tp4@.service"
need_file "deploy/systemd/ds4-preflight-tp4-strict@.service"
need_file "deploy/systemd/ds4-support-bundle@.service"
need_file "deploy/systemd/ds4-preflight@.timer"
need_file "deploy/systemd/ds4-preflight-strict@.timer"
need_file "deploy/systemd/ds4-preflight-tp3@.timer"
need_file "deploy/systemd/ds4-preflight-tp3-strict@.timer"
need_file "deploy/systemd/ds4-preflight-tp4@.timer"
need_file "deploy/systemd/ds4-preflight-tp4-strict@.timer"
need_file "deploy/systemd/ds4-support-bundle@.timer"

need_file "deploy/systemd-user/ds4@.service"
need_file "deploy/systemd-user/ds4-strict@.service"
need_file "deploy/systemd-user/ds4-tp3-strict@.service"
need_file "deploy/systemd-user/ds4-tp4-strict@.service"
need_file "deploy/systemd-user/ds4-preflight@.service"
need_file "deploy/systemd-user/ds4-preflight-strict@.service"
need_file "deploy/systemd-user/ds4-preflight-tp3@.service"
need_file "deploy/systemd-user/ds4-preflight-tp3-strict@.service"
need_file "deploy/systemd-user/ds4-preflight-tp4@.service"
need_file "deploy/systemd-user/ds4-preflight-tp4-strict@.service"
need_file "deploy/systemd-user/ds4-preflight@.timer"
need_file "deploy/systemd-user/ds4-preflight-strict@.timer"
need_file "deploy/systemd-user/ds4-preflight-tp3@.timer"
need_file "deploy/systemd-user/ds4-preflight-tp3-strict@.timer"
need_file "deploy/systemd-user/ds4-preflight-tp4@.timer"
need_file "deploy/systemd-user/ds4-preflight-tp4-strict@.timer"
need_file "deploy/systemd-user/ds4-support-bundle@.service"
need_file "deploy/systemd-user/ds4-support-bundle@.timer"

need_file "deploy/config/ds4.env.example"
need_file "deploy/config/ds4-spark0.env.example"
need_file "deploy/config/ds4-spark1.env.example"
need_file "deploy/config/ds4-spark2.env.example"
need_file "deploy/config/ds4-spark3.env.example"
need_file "deploy/config/ds4-spark0.tp3.env.example"
need_file "deploy/config/ds4-spark1.tp3.env.example"
need_file "deploy/config/ds4-spark2.tp3.env.example"
need_file "deploy/config/ds4-spark0.tp4.env.example"
need_file "deploy/config/ds4-spark1.tp4.env.example"
need_file "deploy/config/ds4-spark2.tp4.env.example"
need_file "deploy/config/ds4-spark3.tp4.env.example"
need_file "deploy/config/ds4-spark0.conf.example"
need_file "deploy/config/ds4-spark1.conf.example"
need_file "deploy/config/ds4-spark2.conf.example"
need_file "deploy/config/ds4-spark3.conf.example"
need_file "deploy/config/journald.ds4.conf.example"
need_file "deploy/config/logrotate.ds4.conf.example"
need_file "deploy/config/prometheus-scrape.ds4.yml.example"
need_file "deploy/config/hosts.ds4.spark01.example"
need_file "deploy/config/hosts.ds4.spark012.example"
need_file "deploy/config/hosts.ds4.spark_ring.example"
need_file "deploy/config/ssh_config.ds4.spark01.example"
need_file "deploy/config/ssh_config.ds4.spark012.example"
need_file "deploy/config/ssh_config.ds4.spark_ring.example"
need_file "deploy/config/sysctl.ds4.conf.example"

need_file "scripts/ops_stage_deploy_assets.sh"
need_file "scripts/ops_stage_spark0_spark1.sh"
need_file "scripts/ops_stage_spark0_spark1_spark2.sh"
need_file "scripts/ops_stage_spark_ring.sh"
need_file "scripts/ops_ds4_env_check.sh"
need_file "scripts/ops_ds4_config_check.sh"
need_file "scripts/ops_tp2_readiness.sh"
need_file "scripts/ops_tp3_readiness.sh"
need_file "scripts/ops_tp4_readiness.sh"
need_file "scripts/ops_spark_standalone_check.sh"
need_file "scripts/ops_spark01_mesh_check.sh"
need_file "scripts/ops_spark012_mesh_check.sh"
need_file "scripts/ops_spark_ring_mesh_check.sh"
need_file "scripts/ops_collect_support_bundle.sh"
need_file "scripts/ops_validate_staged_assets.sh"
need_file "scripts/ops_validate_installed_assets.sh"
need_file "scripts/ops_install_staged_assets.sh"

echo "== sh -n (ops scripts) =="
sh -n scripts/ops_stage_deploy_assets.sh
sh -n scripts/ops_stage_spark0_spark1.sh
sh -n scripts/ops_stage_spark0_spark1_spark2.sh
sh -n scripts/ops_stage_spark_ring.sh
sh -n scripts/ops_ds4_env_check.sh
sh -n scripts/ops_ds4_config_check.sh
sh -n scripts/ops_tp2_readiness.sh
sh -n scripts/ops_tp3_readiness.sh
sh -n scripts/ops_tp4_readiness.sh
sh -n scripts/ops_spark_standalone_check.sh
sh -n scripts/ops_spark01_mesh_check.sh
sh -n scripts/ops_spark012_mesh_check.sh
sh -n scripts/ops_spark_ring_mesh_check.sh
sh -n scripts/ops_collect_support_bundle.sh
sh -n scripts/ops_validate_deploy_assets.sh
sh -n scripts/ops_validate_staged_assets.sh
sh -n scripts/ops_validate_installed_assets.sh
sh -n scripts/ops_install_staged_assets.sh

echo "== env examples include required keys =="
for env in \
	deploy/config/ds4.env.example \
	deploy/config/ds4-spark0.env.example \
	deploy/config/ds4-spark1.env.example \
	deploy/config/ds4-spark2.env.example \
	deploy/config/ds4-spark3.env.example \
	deploy/config/ds4-spark0.tp3.env.example \
	deploy/config/ds4-spark1.tp3.env.example \
	deploy/config/ds4-spark2.tp3.env.example \
	deploy/config/ds4-spark0.tp4.env.example \
	deploy/config/ds4-spark1.tp4.env.example \
	deploy/config/ds4-spark2.tp4.env.example \
	deploy/config/ds4-spark3.tp4.env.example \
	; do
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
