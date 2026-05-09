# Deploy Assets

This folder contains **templates and examples** for deploying DS4 on Spark0/Spark1.

Nothing here is applied automatically. A human should copy files onto the Sparks,
edit host-specific values, then enable services with `systemctl`.

## Suggested Host Layout

- `/opt/ds4/` : DS4 code + binaries (owned by root, read-only at runtime)
- `/etc/ds4/` : instance configs + environment files (owned by root; readable by `ds4`, e.g. `root:ds4 0750` + `root:ds4 0640`)
- `/var/lib/ds4/` : state (model cache, checkpoints, etc.)
- `/var/log/ds4/` : optional file logs (journald is preferred)

## Systemd Units

`deploy/systemd/` contains systemd templates:

- `ds4@.service` expects:
  - an optional shared env file at `/etc/ds4/ds4.env`
  - an env file at `/etc/ds4/ds4-%i.env` (loaded after `ds4.env`)
  - a config file at `/etc/ds4/ds4-%i.yaml` (may be minimal `{}` until the schema is defined)
  - safe helper scripts at `/opt/ds4/scripts/` (staged by `scripts/ops_stage_deploy_assets.sh`)
  - `ExecStartPre` validates `ds4.env` (when present) and `ds4-%i.env`
- Optional: `ds4-strict@.service` is like `ds4@.service` but *requires* `ds4-preflight-strict@%i.service` before start (fails start if strict preflight fails).
- Optional: `ds4-preflight@.timer` runs non-destructive preflight on boot and periodically after.
- Optional: `ds4-preflight-strict@.timer` runs strict preflight on boot and periodically after.
- Optional: `ds4-support-bundle@.service` collects a non-destructive support bundle (triggered automatically when `ds4-preflight-strict@.service` fails; can also be started manually).
- Optional Spark standalone examples:
  - `spark-master@.service`
  - `spark-worker@.service`

The `%i` instance name should match the host role, e.g. `spark0` or `spark1`.

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
- `ds4-spark0.yaml.example`, `ds4-spark1.yaml.example` : runtime config placeholders (schema TBD)
- `journald.ds4.conf.example` : optional journald persistence/tuning drop-in
- `prometheus-scrape.ds4.yml.example` : example Prometheus scrape config snippet
- `hosts.ds4.spark01.example` : optional `/etc/hosts` pinning for wired Spark0/Spark1
- `spark-spark0.env.example`, `spark-spark1.env.example` : optional Spark standalone env starting points

Copy these to `/etc/ds4/` and remove secrets before committing anything.

If you want shared defaults across instances, copy `ds4.env.example` to `/etc/ds4/ds4.env` and keep instance-specific keys in `ds4-%i.env`.

## Staging Helper

`scripts/ops_stage_deploy_assets.sh` rsyncs templates to `/tmp` on a Spark and
prints the next `sudo` commands to apply them. By default it only installs `ds4*.service` units; Spark units are staged but optional.

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
