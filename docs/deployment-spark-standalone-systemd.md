# Deployment: Spark Standalone via systemd (Optional)

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

This is optional: DS4 can run under systemd without managing Spark via systemd.

## What This Provides

Templates under `deploy/systemd/`:

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

This stages Spark templates under `/tmp/ds4-systemd/` and env examples under `/tmp/ds4-config/`.

If you're already staging Spark0/Spark1/Spark2 for TP=3, you can use the three-host wrapper and then install Spark units via the staged installer:

```bash
./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark2 --install-spark-units
```

## Install (Spark Side, Human Runbook)

1) Install the Spark env file for the instance:

```bash
sudo install -g ds4 -m 0640 /tmp/ds4-config/spark-spark0.env.example /etc/ds4/spark-spark0.env
```

2) Review the units, then install them:

```bash
sudo install -m 0644 /tmp/ds4-systemd/spark-*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

3) Sanity check (non-destructive):

```bash
/opt/ds4/scripts/ops_spark_standalone_check.sh --role master --env /etc/ds4/spark-spark0.env
```

4) Enable/start (example):

```bash
sudo systemctl enable spark-master@spark0.service
sudo systemctl start  spark-master@spark0.service

sudo systemctl enable spark-worker@spark0.service
sudo systemctl start  spark-worker@spark0.service
```

## Logs

If using the systemd templates in this repo, you can filter by unit or by the `SyslogIdentifier` tag:

```bash
journalctl -u spark-master@spark0.service -n 200 --no-pager
journalctl -u spark-worker@spark0.service -n 200 --no-pager
journalctl -t spark-master-spark0 -n 200 --no-pager
journalctl -t spark-worker-spark0 -n 200 --no-pager
```

## Notes

- These templates assume Spark is installed at `${SPARK_HOME}` and provides `bin/spark-class`.
- The units run as `ds4` by default for convenience; adjust `User=`/`Group=` to match your Spark packaging.
- Port conventions are listed in `docs/ops-spark0-spark1-network-ports.md`.
