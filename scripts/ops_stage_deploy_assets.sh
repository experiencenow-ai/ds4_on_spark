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

rsync -av "$root/deploy/systemd/" "$target:/tmp/ds4-systemd/"
rsync -av "$root/deploy/config/" "$target:/tmp/ds4-config/"
rsync -av "$root/scripts/ops_tp2_readiness.sh" "$target:/tmp/ops_tp2_readiness.sh"

cat <<EOF

== next (on Spark, human-run) ==
sudo install -m 0644 /tmp/ds4-systemd/*.service /etc/systemd/system/
sudo install -m 0640 /tmp/ds4-config/ds4-${instance}.env.example /etc/ds4/ds4-${instance}.env
sudo install -d -m 0755 /opt/ds4/scripts
sudo install -m 0755 /tmp/ops_tp2_readiness.sh /opt/ds4/scripts/ops_tp2_readiness.sh
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight@${instance}.service
EOF
