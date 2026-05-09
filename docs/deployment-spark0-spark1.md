# Deployment: Spark0 + Spark1 (TP=2 Prep)

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

Goal: make it easy to stand up a repeatable Spark0/Spark1 layout with systemd templates, consistent logs/metrics, and safe preflight checks.

## Roles + Naming

- Spark0: initial single-box development + eventual TP=2 rank 0 (`ds4@spark0`)
- Spark1: TP=2 rank 1 (`ds4@spark1`)

Keep instance names stable: `%i` in systemd maps to `/etc/ds4/ds4-%i.env`.

## On Each Spark: Minimal Filesystem Bring-up

Pick one approach and run it on **both** Sparks.

### Option A: Manual (works everywhere)

```bash
sudo useradd --system --home /nonexistent --shell /usr/sbin/nologin ds4 || true
sudo install -d -o root -g root -m 0755 /opt/ds4
sudo install -d -o root -g ds4  -m 0750 /etc/ds4
```

The `ds4@.service` template uses systemd-managed `StateDirectory=` / `LogsDirectory=` (created automatically) for `/var/lib/ds4` and `/var/log/ds4`.

### Option B: sysusers/tmpfiles (if present in your checkout)

If your checkout contains `deploy/sysusers.d/` and `deploy/tmpfiles.d/`, you can install those templates instead of running `useradd` / `install -d` by hand. See the templates for exact commands (still human-run).

## Stage Templates From Your Mac

From this repo root (on the Mac):

```bash
./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0
./scripts/ops_stage_deploy_assets.sh spark1@<spark1-host> spark1
```

This copies systemd templates + config examples to `/tmp/` on each Spark and prints the next human-run commands.

It also stages safe ops scripts (preflight + env sanity checks) under `/tmp/ds4-scripts/`.

## On Each Spark: Install Systemd + Config

If you want repeatable user/dir bring-up via sysusers/tmpfiles, run the `sysusers.d`/`tmpfiles.d` install commands printed by `ops_stage_deploy_assets.sh` first.

On Spark0:

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4*.service /etc/systemd/system/
# optional (shared defaults loaded before per-instance env; do not overwrite if already customized):
# if [ ! -f /etc/ds4/ds4.env ]; then sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4.env.example /etc/ds4/ds4.env; fi
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark0.env.example /etc/ds4/ds4-spark0.env
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark0.yaml.example /etc/ds4/ds4-spark0.yaml
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight@spark0.service
```

On Spark1:

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4*.service /etc/systemd/system/
# optional (shared defaults loaded before per-instance env; do not overwrite if already customized):
# if [ ! -f /etc/ds4/ds4.env ]; then sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4.env.example /etc/ds4/ds4.env; fi
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark1.env.example /etc/ds4/ds4-spark1.env
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark1.yaml.example /etc/ds4/ds4-spark1.yaml
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight@spark1.service
```

Notes:

- The YAML config examples are intentionally minimal until the DS4 config schema is defined in-tree.
- `ds4@.service` is wired to *want* the preflight unit for the same instance; you can run preflight independently at any time.

## Optional: Env Sanity Check (Spark Side)

Before enabling long-running services, you can validate the env file contents:

```bash
sudo /opt/ds4/scripts/ops_ds4_env_check.sh /etc/ds4/ds4-spark0.env
```

If you haven't installed scripts under `/opt/ds4/scripts/` yet, run directly from the repo checkout:

```bash
sudo ./scripts/ops_ds4_env_check.sh /etc/ds4/ds4-spark0.env
```

## Enable/Start Services

Once `/opt/ds4/bin/ds4_server` exists and the runtime flags are stable:

```bash
sudo systemctl enable ds4@spark0.service
sudo systemctl start  ds4@spark0.service

sudo systemctl enable ds4@spark1.service
sudo systemctl start  ds4@spark1.service
```

Logs:

```bash
journalctl -u ds4@spark0.service -n 200 --no-pager
journalctl -u ds4-preflight@spark0.service -n 200 --no-pager
```

## Conventions + Runbooks

- Logging + metrics: `docs/ops-logging-metrics.md`
- SSH + network: `docs/ops-ssh-network-runbook.md`
- TP=2 readiness checklist: `docs/ops-tp2-readiness.md`
- Optional Spark standalone systemd: `docs/deployment-spark-standalone-systemd.md`
