#!/usr/bin/env sh
set -eu

target="${1:-}"
if [ "$target" = "" ]; then
    echo "usage: ops_stage_deploy_assets.sh <user@host> [instance]" >&2
    echo "note: if instance omitted, inferred from host prefix (e.g. spark0.local -> spark0)" >&2
    echo "env: SSH_OPTS (optional ssh options override)" >&2
    exit 2
fi

instance="${2:-}"
if [ "$instance" = "" ]; then
    case "$target" in
        *@*)
            host="${target#*@}"
            instance="${host%%.*}"
            ;;
        *)
            instance="${target%%.*}"
            ;;
    esac
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "== staging deploy assets to $target (instance=$instance) =="

if [ "${DS4_SKIP_VALIDATE:-}" = "" ]; then
    if [ -x "$root/scripts/ops_validate_deploy_assets.sh" ]; then
        "$root/scripts/ops_validate_deploy_assets.sh"
    fi
fi

if [ "${SSH_OPTS:-}" = "" ]; then
    known_hosts="/tmp/ds4_spark_known_hosts"
    if [ -d "/private/tmp" ]; then
        known_hosts="/private/tmp/ds4_spark_known_hosts"
    fi
    SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$known_hosts"
fi

ssh_run()
{
    target="$1"
    shift
    ssh $SSH_OPTS "$target" "$@"
}

rsync_run()
{
    rsync -av -e "ssh $SSH_OPTS" "$@"
}

ssh_run "$target" "mkdir -p /tmp/ds4-systemd /tmp/ds4-config /tmp/ds4-sysusers /tmp/ds4-tmpfiles /tmp/ds4-scripts"

rsync_run "$root/deploy/systemd/" "$target:/tmp/ds4-systemd/"
rsync_run "$root/deploy/config/" "$target:/tmp/ds4-config/"
rsync_run "$root/deploy/sysusers.d/" "$target:/tmp/ds4-sysusers/"
rsync_run "$root/deploy/tmpfiles.d/" "$target:/tmp/ds4-tmpfiles/"
rsync_run "$root/scripts/ops_tp2_readiness.sh" "$target:/tmp/ds4-scripts/"
rsync_run "$root/scripts/ops_ds4_env_check.sh" "$target:/tmp/ds4-scripts/"
rsync_run "$root/scripts/ops_ds4_config_check.sh" "$target:/tmp/ds4-scripts/"
rsync_run "$root/scripts/ops_spark_standalone_check.sh" "$target:/tmp/ds4-scripts/"
rsync_run "$root/scripts/ops_collect_support_bundle.sh" "$target:/tmp/ds4-scripts/"
rsync_run "$root/scripts/ops_validate_staged_assets.sh" "$target:/tmp/ds4-scripts/"
rsync_run "$root/scripts/ops_validate_installed_assets.sh" "$target:/tmp/ds4-scripts/"
rsync_run "$root/scripts/ops_install_staged_assets.sh" "$target:/tmp/ds4-scripts/"

cat <<EOF

== quick install (on Spark, human-run) ==
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance ${instance} --start-preflight
# optional: add --install-timers, --install-spark-units, and/or --strict

== manual step-by-step (equivalent, on Spark, human-run) ==
sudo install -d -m 0755 /etc/sysusers.d /etc/tmpfiles.d
sudo install -m 0644 /tmp/ds4-sysusers/ds4.conf /etc/sysusers.d/ds4.conf
sudo install -m 0644 /tmp/ds4-tmpfiles/ds4.conf /etc/tmpfiles.d/ds4.conf
sudo systemd-sysusers || true
sudo systemd-tmpfiles --create || true

== optional (validate staged assets before install, human-run) ==
/tmp/ds4-scripts/ops_validate_staged_assets.sh

sudo install -m 0644 /tmp/ds4-systemd/ds4*.service /etc/systemd/system/
# optional (shared defaults loaded before per-instance env; do not overwrite if already customized):
# if [ ! -f /etc/ds4/ds4.env ]; then sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4.env.example /etc/ds4/ds4.env; fi
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-${instance}.env.example /etc/ds4/ds4-${instance}.env
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-${instance}.conf.example /etc/ds4/ds4-${instance}.conf
sudo install -d -m 0755 /opt/ds4/scripts
sudo install -m 0755 /tmp/ds4-scripts/ops_tp2_readiness.sh /opt/ds4/scripts/ops_tp2_readiness.sh
sudo install -m 0755 /tmp/ds4-scripts/ops_ds4_env_check.sh /opt/ds4/scripts/ops_ds4_env_check.sh
sudo install -m 0755 /tmp/ds4-scripts/ops_ds4_config_check.sh /opt/ds4/scripts/ops_ds4_config_check.sh
sudo install -m 0755 /tmp/ds4-scripts/ops_spark_standalone_check.sh /opt/ds4/scripts/ops_spark_standalone_check.sh
sudo install -m 0755 /tmp/ds4-scripts/ops_collect_support_bundle.sh /opt/ds4/scripts/ops_collect_support_bundle.sh
sudo /opt/ds4/scripts/ops_ds4_env_check.sh -/etc/ds4/ds4.env /etc/ds4/ds4-${instance}.env
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight@${instance}.service

== optional (strict TP=2 readiness gating, human-run) ==
# Fails non-zero if required TP=2 inputs are missing/invalid.
sudo systemctl start ds4-preflight-strict@${instance}.service

== optional (strict DS4 start, human-run) ==
# Starts DS4 only after strict preflight succeeds.
# NOTE: `ds4-strict@.service` is a separate unit template (installed by the `ds4*.service` glob above).
sudo systemctl enable ds4-strict@${instance}.service
sudo systemctl start  ds4-strict@${instance}.service

== optional (periodic preflight timer, human-run) ==
# Runs non-destructive preflight on boot and periodically after.
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight@${instance}.timer

== optional (periodic strict preflight timer, human-run) ==
# Runs strict (fails non-zero on missing/invalid TP=2 inputs) preflight on boot and periodically after.
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-strict@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight-strict@${instance}.timer

== optional (Spark standalone systemd, human-run) ==
sudo install -m 0644 /tmp/ds4-systemd/spark-*.service /etc/systemd/system/
sudo install -g ds4 -m 0640 /tmp/ds4-config/spark-${instance}.env.example /etc/ds4/spark-${instance}.env
sudo /opt/ds4/scripts/ops_spark_standalone_check.sh --role worker --env /etc/ds4/spark-${instance}.env --master-host spark0.local

== optional (validate installed assets, human-run) ==
# Confirms installed systemd templates + /etc/ds4 configs are consistent, then runs preflight.
# You can run from /tmp or install it under /opt/ds4/scripts/ for convenience.
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance ${instance}
#sudo install -m 0755 /tmp/ds4-scripts/ops_validate_installed_assets.sh /opt/ds4/scripts/ops_validate_installed_assets.sh
#/opt/ds4/scripts/ops_validate_installed_assets.sh --instance ${instance}

== optional (collect a support bundle, human-run) ==
# Useful when preflight fails or logs/metrics look suspicious (non-destructive; review bundle before sharing).
/opt/ds4/scripts/ops_collect_support_bundle.sh --instance ${instance} --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-${instance}.env

== optional (periodic support bundle timer, human-run) ==
# Captures a support bundle periodically (defaults to weekly with a randomized delay).
# Bundles land in /tmp by default; review disk/retention expectations before enabling.
sudo install -m 0644 /tmp/ds4-systemd/ds4-support-bundle@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-support-bundle@${instance}.timer

== optional (journald persistence, human-run) ==
sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo install -m 0644 /tmp/ds4-config/journald.ds4.conf.example /etc/systemd/journald.conf.d/ds4.conf
sudo systemctl restart systemd-journald

== optional (logrotate for file logs, human-run) ==
# Skip if DS4 logs exclusively to journald.
sudo install -m 0644 /tmp/ds4-config/logrotate.ds4.conf.example /etc/logrotate.d/ds4
sudo logrotate -d /etc/logrotate.d/ds4 || true

== optional (Prometheus scrape snippet, human-run) ==
# Merge this into your Prometheus config and reload Prometheus.
cat /tmp/ds4-config/prometheus-scrape.ds4.yml.example

== optional (sysctl network tuning, human-run) ==
# Host-wide settings; review before applying.
sudo install -m 0644 /tmp/ds4-config/sysctl.ds4.conf.example /etc/sysctl.d/99-ds4.conf
sudo sysctl --system

== optional (pin Spark0/Spark1 hostnames, human-run) ==
# Use only if you are NOT relying on mDNS (`*.local`) and you have a stable wired subnet.
# Review, then append to /etc/hosts on each Spark:
cat /tmp/ds4-config/hosts.ds4.spark01.example
EOF
