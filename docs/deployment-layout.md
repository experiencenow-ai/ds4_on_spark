# Deployment Layout (Spark0/Spark1)

This repo does not apply changes to Sparks automatically. Treat everything here
as **human-run** instructions and templates.

## Host Roles

- Spark0: initial single-box development + eventual TP=2 rank 0
- Spark1: TP=2 rank 1 (bring-up later)

Keep hostnames stable. Prefer mDNS (`*.local`) early; switch to wired IPv4 once
the wired subnet is standardized.

## Filesystem Layout

Suggested DS4 layout on each Spark:

- `/opt/ds4/` : code + binaries (root-owned, read-only at runtime)
- `/opt/ds4/scripts/` : safe ops helpers (root-owned, 0755)
- `/etc/ds4/` : config and env files (root-owned, 0640)
- `/var/lib/ds4/` : state (model cache, checkpoints, artifacts)
- `/var/log/ds4/` : optional file logs (journald is preferred)

## Minimal Setup (Human Runbook)

On each Spark:

1. Create a dedicated service user and directories.

Option A: use systemd sysusers/tmpfiles (recommended for repeatability, after staging deploy assets to `/tmp`):

```bash
sudo install -d -m 0755 /etc/sysusers.d /etc/tmpfiles.d
sudo install -m 0644 /tmp/ds4-sysusers/ds4.conf /etc/sysusers.d/ds4.conf
sudo install -m 0644 /tmp/ds4-tmpfiles/ds4.conf /etc/tmpfiles.d/ds4.conf
sudo systemd-sysusers || true
sudo systemd-tmpfiles --create || true
```

Option B: manual user + dirs:

```bash
sudo useradd --system --home /nonexistent --shell /usr/sbin/nologin ds4 || true
sudo install -d -o root -g root -m 0755 /opt/ds4
sudo install -d -o root -g ds4  -m 0750 /etc/ds4
sudo install -d -o ds4  -g ds4  -m 0750 /var/lib/ds4
sudo install -d -o ds4  -g ds4  -m 0750 /var/log/ds4
```

2. Copy templates from this repo into place.

```bash
# From your Mac:
rsync -av deploy/systemd/ <user>@spark0.local:/tmp/ds4-systemd/
rsync -av deploy/config/  <user>@spark0.local:/tmp/ds4-config/
rsync -av deploy/sysusers.d/ <user>@spark0.local:/tmp/ds4-sysusers/
rsync -av deploy/tmpfiles.d/ <user>@spark0.local:/tmp/ds4-tmpfiles/
```

If you prefer a single command that also stages safe ops scripts, use `scripts/ops_stage_deploy_assets.sh` (it supports `SSH_OPTS` for stable known-hosts handling).

Then on the Spark:

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4*.service /etc/systemd/system/
# optional (shared defaults loaded before per-instance env; do not overwrite if already customized):
# if [ ! -f /etc/ds4/ds4.env ]; then sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4.env.example /etc/ds4/ds4.env; fi
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark0.env.example /etc/ds4/ds4-spark0.env
sudo install -g ds4 -m 0640 /tmp/ds4-config/ds4-spark0.yaml.example /etc/ds4/ds4-spark0.yaml
sudo install -d -m 0755 /opt/ds4/scripts
sudo install -m 0755 /tmp/ds4-scripts/ops_tp2_readiness.sh /opt/ds4/scripts/ops_tp2_readiness.sh
sudo install -m 0755 /tmp/ds4-scripts/ops_ds4_env_check.sh /opt/ds4/scripts/ops_ds4_env_check.sh
sudo systemctl daemon-reload
```

3. Install DS4 binaries under `/opt/ds4/bin/` once available.

The systemd unit in `deploy/systemd/ds4@.service` expects:

- `/opt/ds4/bin/ds4_server`
- optional shared env at `/etc/ds4/ds4.env`
- `/etc/ds4/ds4-spark0.env`
- optional config at `/etc/ds4/ds4-spark0.yaml`

## Safety Notes

- Do not put secrets in the repo. Keep `/etc/ds4/*.env` local to each Spark.
- Prefer journald over file logs until retention/rotation is designed.
- Tighten systemd sandboxing only after CUDA + distributed smoke tests pass.
- Optional Spark standalone systemd templates exist, but are not required for DS4: `docs/deployment-spark-standalone-systemd.md`.
- Optional periodic preflight systemd timer exists: `deploy/systemd/ds4-preflight@.timer`.
- Optional strict start template exists (wants strict preflight before start): `deploy/systemd/ds4-strict@.service`.
