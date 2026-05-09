# Systemd Templates

Templates live in `deploy/systemd/` and are meant to be copied to:

- `/etc/systemd/system/`

They are **examples**. Adjust flags and sandboxing once the runtime interface is
stable.

Optional (recommended): validate deploy assets + ops scripts before staging:

```bash
./scripts/ops_validate_deploy_assets.sh
```

## Units

- `ds4@.service`: long-running DS4 instance
- `ds4-strict@.service`: long-running DS4 instance that *wants* `ds4-preflight-strict@%i.service` before start
- `ds4-preflight@.service`: oneshot readiness checks (safe to run repeatedly)
- `ds4-preflight-strict@.service`: oneshot readiness checks that fail fast on missing/invalid TP=2 inputs (see `docs/ops-tp2-readiness.md`)
- Optional: `ds4-preflight@.timer`: periodic non-destructive preflight
- Optional: `ds4-preflight-strict@.timer`: periodic strict preflight
- Optional Spark standalone helpers: `spark-master@.service`, `spark-worker@.service` (see `docs/deployment-spark-standalone-systemd.md`)

## Instance Naming

Use instance names matching the host role:

- `ds4@spark0`
- `ds4@spark1`

Each instance loads `/etc/ds4/ds4-%i.env` via `EnvironmentFile=`.
Optionally, you can also provide shared defaults in `/etc/ds4/ds4.env` (loaded before `ds4-%i.env`).

The templates set `DS4_INSTANCE=%i` by default, so `ds4-%i.env` may omit `DS4_INSTANCE` if you prefer (the sample env files include it for clarity).

## Prereqs (Human Runbook)

Before starting services, ensure the `ds4` user and base directories exist.

If you stage assets to `/tmp` (see `scripts/ops_stage_deploy_assets.sh`), you can
use the included sysusers/tmpfiles templates:

```bash
sudo install -d -m 0755 /etc/sysusers.d /etc/tmpfiles.d
sudo install -m 0644 /tmp/ds4-sysusers/ds4.conf /etc/sysusers.d/ds4.conf
sudo install -m 0644 /tmp/ds4-tmpfiles/ds4.conf /etc/tmpfiles.d/ds4.conf
sudo systemd-sysusers || true
sudo systemd-tmpfiles --create || true
```

The staging helper also copies safe ops scripts to `/tmp/ds4-scripts/`; install them under `/opt/ds4/scripts/` so systemd units can reference them.

Ensure `/etc/ds4/` and any `/etc/ds4/ds4-*.env` files are readable by the `ds4` service user (recommended: directory `root:ds4 0750`, files `root:ds4 0640`).

## Enable/Start (Human Runbook)

```bash
sudo systemctl daemon-reload
sudo systemctl start  ds4-preflight@spark0.service

sudo systemctl enable ds4@spark0.service
sudo systemctl start  ds4@spark0.service
```

If you want strict TP=2 gating on start, enable the strict service instead:

```bash
sudo systemctl enable ds4-strict@spark0.service
sudo systemctl start  ds4-strict@spark0.service
```

Inspect logs:

```bash
journalctl -u ds4@spark0.service -n 200 --no-pager
journalctl -u ds4-preflight@spark0.service -n 200 --no-pager
```

For optional journald persistence, file-log rotation, and Prometheus scrape conventions, see `docs/ops-logging-metrics.md` and the examples under `deploy/config/`.

## Hardening Guidance

`deploy/systemd/ds4@.service` includes conservative sandboxing. Avoid enabling
`MemoryDenyWriteExecute=` until CUDA JIT behavior is fully understood.
