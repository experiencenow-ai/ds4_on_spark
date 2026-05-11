# Deployment: Spark Standalone via `systemd --user` (Optional)

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

This is optional: DS4 can run under systemd without managing Spark via systemd.

This document covers a non-root Spark standalone bring-up via `systemd --user`.

## What This Provides

Templates under `deploy/systemd-user/`:

- `spark-master@.service`
- `spark-worker@.service`

Config examples under `deploy/config/`:

- `spark-spark0.env.example`
- `spark-spark1.env.example`
- `spark-spark2.env.example`

Safe checker script:

- `scripts/ops_spark_standalone_check.sh`

## Stage Assets From Your Mac

From this repo root (on the Mac):

```bash
./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0
./scripts/ops_stage_deploy_assets.sh spark1@<spark1-host> spark1
./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2
```

This stages Spark user templates under `/tmp/ds4-systemd-user/` and env examples under `/tmp/ds4-config/`.

## Install (Spark Side, Human Runbook)

1) Install the Spark env file for the instance:

```bash
install -d -m 0755 ~/.config/ds4
install -m 0640 /tmp/ds4-config/spark-spark0.env.example ~/.config/ds4/spark-spark0.env
```

2) Install the user-service templates:

```bash
install -d -m 0755 ~/.config/systemd/user
install -m 0644 /tmp/ds4-systemd-user/spark-*.service ~/.config/systemd/user/
systemctl --user daemon-reload
```

Alternative: the staged helper installer can do the same copy steps:

```bash
/tmp/ds4-scripts/ops_install_staged_assets_user.sh --instance spark0 --install-spark-units
```

3) Sanity check (non-destructive):

```bash
$HOME/ds4/scripts/ops_spark_standalone_check.sh --role master --env ~/.config/ds4/spark-spark0.env
```

4) Enable/start (example):

```bash
systemctl --user enable --now spark-master@spark0.service
systemctl --user enable --now spark-worker@spark0.service
```

For Spark1/Spark2, install `~/.config/ds4/spark-spark1.env` / `spark-spark2.env` and start `spark-worker@spark1.service` / `spark-worker@spark2.service`.

## Logs

If using the `systemd --user` templates in this repo, you can filter by unit or by the `SyslogIdentifier` tag:

```bash
journalctl --user -u spark-master@spark0.service -n 200 --no-pager
journalctl --user -u spark-worker@spark1.service -n 200 --no-pager
journalctl --user -t spark-user-master-spark0 -n 200 --no-pager
journalctl --user -t spark-user-worker-spark1 -n 200 --no-pager
```

## Notes

- These templates assume Spark is installed at `${SPARK_HOME}` and provides `bin/spark-class`.
- The user-unit templates read env from `~/.config/ds4/spark-%i.env` (per-instance).
- If you want user services to keep running after logout, see lingering notes in `docs/deployment-systemd-user.md` (host policy dependent; requires human approval).

