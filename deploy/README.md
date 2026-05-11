# Deploy Assets

This folder contains **templates and examples** for deploying DS4 on Spark0/Spark1, preparing a Spark0/Spark1/Spark2 TP=3 layout, and preparing a Spark0..Spark3 ring layout.

Nothing here is applied automatically. A human should copy files onto the Sparks,
edit host-specific values, then enable services with `systemctl`.

## Suggested Host Layout

- `/opt/ds4/` : DS4 code + binaries (owned by root, read-only at runtime)
- `/etc/ds4/` : instance configs + environment files (owned by root; readable by `ds4`, e.g. `root:ds4 0750` + `root:ds4 0640`)
- `/var/lib/ds4/` : state (e.g. `models/` + `cache/`, checkpoints, etc.)
- `/var/log/ds4/` : optional file logs (journald is preferred)

## Systemd Units

`deploy/systemd/` contains systemd templates:

- `ds4@.service` expects:
  - an optional shared env file at `/etc/ds4/ds4.env`
  - an env file at `/etc/ds4/ds4-%i.env` (loaded after `ds4.env`)
  - a config file at `/etc/ds4/ds4-%i.conf` (key=value; see `src/ds4_config.c`)
  - safe helper scripts at `/opt/ds4/scripts/` (staged by `scripts/ops_stage_deploy_assets.sh`)
  - `ExecStartPre` validates `ds4.env` (when present) and `ds4-%i.env`
- Optional: `ds4-strict@.service` is like `ds4@.service` but *requires* `ds4-preflight-strict@%i.service` before start (fails start if strict preflight fails).
- Optional: `ds4-tp3-strict@.service` is like `ds4@.service` but *requires* `ds4-preflight-tp3-strict@%i.service` before start (strict TP=3 gating).
- Optional: `ds4-tp4-strict@.service` is like `ds4@.service` but *requires* `ds4-preflight-tp4-strict@%i.service` before start (strict TP=4 gating).
- Optional: `ds4-preflight@.timer` runs non-destructive preflight on boot and periodically after.
- Optional: `ds4-preflight-strict@.timer` runs strict preflight on boot and periodically after.
- Optional TP=3 helpers:
  - `ds4-preflight-tp3@.service`
  - `ds4-preflight-tp3-strict@.service`
  - `ds4-preflight-tp3@.timer`
  - `ds4-preflight-tp3-strict@.timer`
- Optional TP=4 helpers:
  - `ds4-preflight-tp4@.service`
  - `ds4-preflight-tp4-strict@.service`
  - `ds4-preflight-tp4@.timer`
  - `ds4-preflight-tp4-strict@.timer`
- Optional: `ds4-support-bundle@.service` collects a non-destructive support bundle (triggered automatically when `ds4-preflight-strict@.service` fails; can also be started manually).
- Optional Spark standalone examples:
  - `spark-master@.service`
  - `spark-worker@.service`

The `%i` instance name should match the host role, e.g. `spark0` or `spark1`.

Optional: `deploy/systemd-user/` contains user-service + timer templates for `systemd --user` (developer bring-up). See `docs/deployment-systemd-user.md`.

## Sysusers + Tmpfiles

Optional (recommended) templates for repeatable host bring-up:

- `deploy/sysusers.d/ds4.conf` → `/etc/sysusers.d/ds4.conf`
- `deploy/tmpfiles.d/ds4.conf` → `/etc/tmpfiles.d/ds4.conf`

Then (human-run on Spark):

```bash
sudo systemd-sysusers || true
sudo systemd-tmpfiles --create || true
```

## Config Examples

`deploy/config/` contains:

- `ds4.env.example` : base env keys (single-Spark and dual-Spark placeholders)
- `ds4-spark0.env.example`, `ds4-spark1.env.example` : per-host starting points
- `ds4-spark2.env.example`, `ds4-spark3.env.example` : generic placeholders (see TP-specific variants below)
- TP=3 (Spark0/Spark1/Spark2) starting points:
  - `ds4-spark0.tp3.env.example`, `ds4-spark1.tp3.env.example`, `ds4-spark2.tp3.env.example`
- TP=4 (Spark0..Spark3) starting points:
  - `ds4-spark0.tp4.env.example`, `ds4-spark1.tp4.env.example`, `ds4-spark2.tp4.env.example`, `ds4-spark3.tp4.env.example`
- `ds4-spark0.conf.example`, `ds4-spark1.conf.example`, `ds4-spark2.conf.example`, `ds4-spark3.conf.example` : runtime config placeholders (key=value)
- `journald.ds4.conf.example` : optional journald persistence/tuning drop-in
- `logrotate.ds4.conf.example` : optional logrotate config for file logs (skip if journald-only)
- `prometheus-scrape.ds4.yml.example` : example Prometheus scrape config snippet
- `hosts.ds4.spark01.example` : optional `/etc/hosts` pinning for wired Spark0/Spark1
- `hosts.ds4.spark012.example` : optional `/etc/hosts` pinning for wired Spark0/Spark1/Spark2
- `hosts.ds4.spark_ring.example` : optional `/etc/hosts` pinning for wired Spark0..Spark3
- `ssh_config.ds4.spark01.example` : optional Mac-side `ssh_config` convenience (stable SSH_OPTS)
- `ssh_config.ds4.spark012.example` : optional Mac-side `ssh_config` convenience (Spark0/Spark1/Spark2)
- `ssh_config.ds4.spark_ring.example` : optional Mac-side `ssh_config` convenience (Spark0..Spark3)
- `sysctl.ds4.conf.example` : optional sysctl network tuning drop-in (host-wide; review first)
- `spark-spark0.env.example`, `spark-spark1.env.example`, `spark-spark2.env.example` : optional Spark standalone env starting points

Copy these to `/etc/ds4/` and remove secrets before committing anything.

If you want shared defaults across instances, copy `ds4.env.example` to `/etc/ds4/ds4.env` and keep instance-specific keys in `ds4-%i.env`.

## Staging Helper

`scripts/ops_stage_deploy_assets.sh` rsyncs templates to `/tmp` on a Spark and
prints the next `sudo` commands to apply them. By default it only installs `ds4*.service` units; Spark units are staged but optional.

Optional: when staging, you can ask it to swap a TP-specific env example into place on the Spark:

- `DS4_ENV_VARIANT=tp3` uses `ds4-<instance>.tp3.env.example` when present
- `DS4_ENV_VARIANT=tp4` uses `ds4-<instance>.tp4.env.example` when present

If you're staging both Spark0 and Spark1, prefer the two-host wrapper (avoids instance-name mistakes and can run an optional mesh check first):

```bash
./scripts/ops_stage_spark0_spark1.sh spark0@<spark0-host> spark1@<spark1-host>
# optional: add --mesh-check and/or --tcp <port>
```

If you're staging Spark0/Spark1/Spark2, prefer the three-host wrapper:

```bash
./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
# optional: add --tcp <port>
```

If you're staging Spark0..Spark3, prefer the ring wrapper:

```bash
./scripts/ops_stage_spark_ring.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host> spark3@<spark3-host>
# optional: add --mesh-check --topology ring and/or --tcp <port>
```

Optional: on the Spark, use the staged installer wrapper to apply the staged assets in one command (human-run; review first):

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --start-preflight
# optional: add --preflight tp2|tp3|tp4, --install-timers, --install-spark-units, and/or --strict
```

Before staging, you can sanity-check that deploy assets and ops scripts are internally consistent:

```bash
./scripts/ops_validate_deploy_assets.sh
```

After staging (Spark side), validate the staged `/tmp/ds4-*` directories before installing:

```bash
/tmp/ds4-scripts/ops_validate_staged_assets.sh
```

After installing templates/configs/scripts under `/etc` + `/opt` (Spark side), validate the installed layout and run preflight:

```bash
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark0
```

For stable non-interactive SSH (identity + dedicated known-hosts path), set `SSH_OPTS` before running the staging helper.
