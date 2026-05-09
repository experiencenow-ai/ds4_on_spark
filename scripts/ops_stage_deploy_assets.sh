#!/usr/bin/env sh
set -eu

target="${1:-}"
if [ "$target" = "" ]; then
    echo "usage: ops_stage_deploy_assets.sh <user@host> [instance]" >&2
    exit 2
fi

instance="${2:-}"
if [ "$instance" = "" ]; then
    case "$target" in
        *@*)
            instance="${target%%@*}"
            ;;
        *)
            instance="${target%%.*}"
            ;;
    esac
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo "== staging deploy assets to $target (instance=$instance) =="

ssh "$target" "mkdir -p /tmp/ds4-systemd /tmp/ds4-config /tmp/ds4-sysusers /tmp/ds4-tmpfiles /tmp/ds4-scripts"

rsync -av "$root/deploy/systemd/" "$target:/tmp/ds4-systemd/"
rsync -av "$root/deploy/config/" "$target:/tmp/ds4-config/"
rsync -av "$root/deploy/sysusers.d/" "$target:/tmp/ds4-sysusers/"
rsync -av "$root/deploy/tmpfiles.d/" "$target:/tmp/ds4-tmpfiles/"
rsync -av "$root/scripts/ops_tp2_readiness.sh" "$target:/tmp/ds4-scripts/"
rsync -av "$root/scripts/ops_ds4_env_check.sh" "$target:/tmp/ds4-scripts/"
rsync -av "$root/scripts/ops_spark_standalone_check.sh" "$target:/tmp/ds4-scripts/"

cat <<EOF

== next (on Spark, human-run) ==
sudo install -d -m 0755 /etc/sysusers.d /etc/tmpfiles.d
sudo install -m 0644 /tmp/ds4-sysusers/ds4.conf /etc/sysusers.d/ds4.conf
sudo install -m 0644 /tmp/ds4-tmpfiles/ds4.conf /etc/tmpfiles.d/ds4.conf
sudo systemd-sysusers || true
sudo systemd-tmpfiles --create || true
sudo install -m 0644 /tmp/ds4-systemd/ds4*.service /etc/systemd/system/
# optional (shared defaults loaded before per-instance env; do not overwrite if already customized):
# if [ ! -f /etc/ds4/ds4.env ]; then sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4.env.example /etc/ds4/ds4.env; fi
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-${instance}.env.example /etc/ds4/ds4-${instance}.env
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-${instance}.yaml.example /etc/ds4/ds4-${instance}.yaml
sudo install -d -m 0755 /opt/ds4/scripts
sudo install -m 0755 /tmp/ds4-scripts/ops_tp2_readiness.sh /opt/ds4/scripts/ops_tp2_readiness.sh
sudo install -m 0755 /tmp/ds4-scripts/ops_ds4_env_check.sh /opt/ds4/scripts/ops_ds4_env_check.sh
sudo install -m 0755 /tmp/ds4-scripts/ops_spark_standalone_check.sh /opt/ds4/scripts/ops_spark_standalone_check.sh
sudo /opt/ds4/scripts/ops_ds4_env_check.sh -/etc/ds4/ds4.env /etc/ds4/ds4-${instance}.env
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight@${instance}.service

== optional (Spark standalone systemd, human-run) ==
sudo install -m 0644 /tmp/ds4-systemd/spark-*.service /etc/systemd/system/
sudo install -g ds4 -m 0640 /tmp/ds4-config/spark-${instance}.env.example /etc/ds4/spark-${instance}.env
sudo /opt/ds4/scripts/ops_spark_standalone_check.sh --role worker --env /etc/ds4/spark-${instance}.env --master-host spark0.local

== optional (journald persistence, human-run) ==
sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo install -m 0644 /tmp/ds4-config/journald.ds4.conf.example /etc/systemd/journald.conf.d/ds4.conf
sudo systemctl restart systemd-journald
EOF
