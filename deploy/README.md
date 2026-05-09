# Deploy Assets

This folder contains **templates and examples** for deploying DS4 on Spark0/Spark1.

Nothing here is applied automatically. A human should copy files onto the Sparks,
edit host-specific values, then enable services with `systemctl`.

## Suggested Host Layout

- `/opt/ds4/` : DS4 code + binaries (owned by root, read-only at runtime)
- `/etc/ds4/` : instance configs + environment files (owned by root)
- `/var/lib/ds4/` : state (model cache, checkpoints, etc.)
- `/var/log/ds4/` : optional file logs (journald is preferred)

## Systemd Units

`deploy/systemd/` contains systemd templates:

- `ds4@.service` expects:
  - an optional shared env file at `/etc/ds4/ds4.env`
  - an env file at `/etc/ds4/ds4-%i.env` (loaded after `ds4.env`)
  - an optional config at `/etc/ds4/ds4-%i.yaml`
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
- `spark-spark0.env.example`, `spark-spark1.env.example` : optional Spark standalone env starting points

Copy these to `/etc/ds4/` and remove secrets before committing anything.

If you want shared defaults across instances, copy `ds4.env.example` to `/etc/ds4/ds4.env` and keep instance-specific keys in `ds4-%i.env`.

## Staging Helper

`scripts/ops_stage_deploy_assets.sh` rsyncs templates to `/tmp` on a Spark and
prints the next `sudo` commands to apply them. By default it only installs `ds4*.service` units; Spark units are staged but optional.
