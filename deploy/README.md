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
  - an env file at `/etc/ds4/ds4-%i.env`
  - an optional config at `/etc/ds4/ds4-%i.yaml`

The `%i` instance name should match the host role, e.g. `spark0` or `spark1`.

## Config Examples

`deploy/config/` contains:

- `ds4.env.example` : base env keys (single-Spark and dual-Spark placeholders)
- `ds4-spark0.env.example`, `ds4-spark1.env.example` : per-host starting points

Copy these to `/etc/ds4/` and remove secrets before committing anything.
