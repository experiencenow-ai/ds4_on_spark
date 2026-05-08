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

Safe checker script:

- `scripts/ops_spark_standalone_check.sh`

## Stage Assets From Your Mac

From this repo root (on the Mac):

```bash
./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0
./scripts/ops_stage_deploy_assets.sh spark1@<spark1-host> spark1
```

This stages Spark templates under `/tmp/ds4-systemd/` and env examples under `/tmp/ds4-config/`.

## Install (Spark Side, Human Runbook)

1) Install the Spark env file for the instance:

```bash
sudo install -m 0640 /tmp/ds4-config/spark-spark0.env.example /etc/ds4/spark-spark0.env
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

## Notes

- These templates assume Spark is installed at `${SPARK_HOME}` and provides `bin/spark-class`.
- The units run as `ds4` by default for convenience; adjust `User=`/`Group=` to match your Spark packaging.
- Port conventions are listed in `docs/ops-spark0-spark1-network-ports.md`.

