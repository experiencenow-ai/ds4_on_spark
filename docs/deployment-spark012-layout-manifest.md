# Deployment: Spark0/Spark1/Spark2 Layout Manifest (Reference)

This repo does not apply changes to Sparks automatically. Everything here is **human-run**.

This document introduces a **review/packaging** helper for Spark0/Spark1/Spark2 bring-up:

- `deploy/layout/spark012/system.manifest.tsv`
- `deploy/layout/spark012/user.manifest.tsv`

The manifests provide a mapping from repo assets (systemd templates, example configs, and safe ops scripts) to recommended on-host locations for:

- system units (`/etc/systemd/system/` + `/etc/ds4/` + `/opt/ds4/scripts/`)
- user units (`~/.config/systemd/user/` + `~/.config/ds4/` + `~/ds4/scripts/`)

## Recommended Install Path (Preferred)

Prefer staging + install wrappers instead of copying from the manifest directly:

- Stage from the Mac: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring ...`
- Install on each Spark (review first): `sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance <spark0|spark1|spark2> ...`
- Validate installed assets (safe): `sudo /opt/ds4/scripts/ops_validate_installed_assets.sh --instance spark0 --strict`

See:

- `docs/deployment-spark0-spark1-spark2.md`
- `docs/deployment-spark012-staged-layout.md`
- `docs/spark-ring-ops-checklist-tp3.md`
- `docs/ops-logging-metrics.md`
- `docs/ops-ssh-network-runbook.md`
- `docs/ops-firewall-routing-inspection.md`
- `docs/ops-firewall-allowlist.md`

## Manifest Use Cases

Use the manifests when you need one of the following:

- a quick “what files exist and where do they go?” reference during an incident
- a packaging conversation (future) without changing the staging scripts
- a host audit checklist (“are we missing anything obvious?”)

## Safety Notes

- Treat `.env`/`.conf` files as local host state; do not commit secrets.
- Do not apply systemd/network changes as part of automation loops; document proposed commands for human approval.
