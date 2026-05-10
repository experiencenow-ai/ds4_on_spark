# Deployment: Spark0 + Spark1 (TP=2 Prep)

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

Goal: make it easy to stand up a repeatable Spark0/Spark1 layout with systemd templates, consistent logs/metrics, and safe preflight checks.

## Roles + Naming

- Spark0: initial single-box development + eventual TP=2 rank 0 (`ds4@spark0`)
- Spark1: TP=2 rank 1 (`ds4@spark1`)

Keep instance names stable: `%i` in systemd maps to `/etc/ds4/ds4-%i.env`.
The systemd templates set `DS4_INSTANCE=%i` by default; the sample env files include `DS4_INSTANCE=...` for clarity.

Decide how hosts resolve:

- mDNS (`spark0.local`, `spark1.local`) for early bring-up
- pinned `/etc/hosts` entries for stability on an isolated wired subnet (see `deploy/config/hosts.ds4.spark01.example`)

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

Optional (recommended): validate deploy assets + ops scripts before staging:

```bash
./scripts/ops_validate_deploy_assets.sh
```

From this repo root (on the Mac):

```bash
./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0
./scripts/ops_stage_deploy_assets.sh spark1@<spark1-host> spark1
```

This copies systemd templates + config examples to `/tmp/` on each Spark and prints the next human-run commands.

It also stages safe ops scripts (preflight + env sanity checks) under `/tmp/ds4-scripts/`.

If you prefer a single command to stage both hosts (recommended to avoid instance-name mistakes):

```bash
./scripts/ops_stage_spark0_spark1.sh spark0@<spark0-host> spark1@<spark1-host>
# optional: add --mesh-check and/or --tcp <port>
```

### Optional: Validate Staged Assets (Spark Side)

On each Spark, you can validate the staged `/tmp/ds4-*` directories before installing anything:

```bash
/tmp/ds4-scripts/ops_validate_staged_assets.sh
```

### Optional: SSH Options For Staging

If you want stable non-interactive SSH (identity + dedicated known-hosts path), set `SSH_OPTS`:

```bash
SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts' \
./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0
```

If `SSH_OPTS` is not set, `ops_stage_deploy_assets.sh` uses a safe default with a dedicated known-hosts file under `/private/tmp` (or `/tmp` when `/private/tmp` is absent).

### Optional: Mesh Check Before Staging

If you want a quick sanity check that both Sparks are reachable and can ping each other:

```bash
SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts' \
./scripts/ops_spark01_mesh_check.sh spark0@<spark0-host> spark1@<spark1-host>
```

## On Each Spark: Install Systemd + Config

If you want repeatable user/dir bring-up via sysusers/tmpfiles, run the `sysusers.d`/`tmpfiles.d` install commands printed by `ops_stage_deploy_assets.sh` first.

Recommended: use the staged installer wrapper (human-run; review first). This installs the staged templates into `/etc` + `/opt`, reloads systemd, and can optionally start preflight:

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance <spark0|spark1> --start-preflight
# optional: add --install-timers, --install-spark-units, and/or --strict
```

Manual step-by-step (equivalent):

On Spark0:

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4*.service /etc/systemd/system/
# optional (shared defaults loaded before per-instance env; do not overwrite if already customized):
# if [ ! -f /etc/ds4/ds4.env ]; then sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4.env.example /etc/ds4/ds4.env; fi
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark0.env.example /etc/ds4/ds4-spark0.env
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark0.conf.example /etc/ds4/ds4-spark0.conf
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight@spark0.service
# optional strict variant (fails non-zero on missing/invalid TP=2 inputs):
# sudo systemctl start ds4-preflight-strict@spark0.service
#
# optional periodic preflight timer (runs on boot + periodically after):
# sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight@.timer /etc/systemd/system/
# sudo systemctl daemon-reload
# sudo systemctl enable --now ds4-preflight@spark0.timer
#
# optional periodic strict preflight timer (fails non-zero on missing/invalid TP=2 inputs):
# sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-strict@.timer /etc/systemd/system/
# sudo systemctl daemon-reload
# sudo systemctl enable --now ds4-preflight-strict@spark0.timer
```

On Spark1:

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4*.service /etc/systemd/system/
# optional (shared defaults loaded before per-instance env; do not overwrite if already customized):
# if [ ! -f /etc/ds4/ds4.env ]; then sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4.env.example /etc/ds4/ds4.env; fi
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark1.env.example /etc/ds4/ds4-spark1.env
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark1.conf.example /etc/ds4/ds4-spark1.conf
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight@spark1.service
# optional strict variant (fails non-zero on missing/invalid TP=2 inputs):
# sudo systemctl start ds4-preflight-strict@spark1.service
#
# optional periodic preflight timer (runs on boot + periodically after):
# sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight@.timer /etc/systemd/system/
# sudo systemctl daemon-reload
# sudo systemctl enable --now ds4-preflight@spark1.timer
#
# optional periodic strict preflight timer (fails non-zero on missing/invalid TP=2 inputs):
# sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-strict@.timer /etc/systemd/system/
# sudo systemctl daemon-reload
# sudo systemctl enable --now ds4-preflight-strict@spark1.timer
```

Notes:

- The DS4 config examples are `key=value` placeholders (see `src/ds4_config.c`).
- `ds4@.service` is wired to *want* the preflight unit for the same instance; you can run preflight independently at any time.

## Optional: Validate Installed Assets (Spark Side)

After installing templates under `/etc/systemd/system/`, configs under `/etc/ds4/`, and scripts under `/opt/ds4/scripts/`, you can validate the installed layout and run preflight:

```bash
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark0
```

Use `--strict` if you want fail-fast gating on missing/invalid TP=2 inputs:

```bash
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark0 --strict
```

## Optional: Capture A Support Bundle (Spark Side)

If preflight fails or routing/metrics look suspicious, capture a support bundle (non-destructive; review before sharing):

```bash
/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark0 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env
```

Details: `docs/ops-support-bundle.md`.

## Optional: Env Sanity Check (Spark Side)

Before enabling long-running services, you can validate the env file contents:

```bash
sudo /opt/ds4/scripts/ops_ds4_env_check.sh -/etc/ds4/ds4.env /etc/ds4/ds4-spark0.env
```

If you haven't installed scripts under `/opt/ds4/scripts/` yet, run directly from the repo checkout:

```bash
sudo ./scripts/ops_ds4_env_check.sh -/etc/ds4/ds4.env /etc/ds4/ds4-spark0.env
```

## Enable/Start Services

Once `/opt/ds4/bin/ds4_server` exists and the runtime flags are stable:

```bash
sudo systemctl enable ds4@spark0.service
sudo systemctl start  ds4@spark0.service

sudo systemctl enable ds4@spark1.service
sudo systemctl start  ds4@spark1.service
```

If you want strict TP=2 gating on start, use `ds4-strict@.service` instead:

```bash
sudo systemctl enable ds4-strict@spark0.service
sudo systemctl start  ds4-strict@spark0.service
```

`ds4-strict@.service` requires `ds4-preflight-strict@%i.service`; if strict preflight fails, `ds4-strict@...` will also fail to start.

Logs:

```bash
journalctl -u ds4@spark0.service -n 200 --no-pager
journalctl -u ds4-preflight@spark0.service -n 200 --no-pager
```

## Conventions + Runbooks

- Logging + metrics: `docs/ops-logging-metrics.md`
- SSH + network: `docs/ops-ssh-network-runbook.md`
- TP=2 readiness checklist: `docs/ops-tp2-readiness.md`
- Optional sysctl network tuning: `docs/ops-sysctl-network-tuning.md`
- Optional Spark standalone systemd: `docs/deployment-spark-standalone-systemd.md`
