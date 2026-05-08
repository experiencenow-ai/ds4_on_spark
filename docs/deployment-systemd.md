# Systemd Templates

Templates live in `deploy/systemd/` and are meant to be copied to:

- `/etc/systemd/system/`

They are **examples**. Adjust flags and sandboxing once the runtime interface is
stable.

## Units

- `ds4@.service`: long-running DS4 instance
- `ds4-preflight@.service`: oneshot readiness checks (safe to run repeatedly)

## Instance Naming

Use instance names matching the host role:

- `ds4@spark0`
- `ds4@spark1`

Each instance loads `/etc/ds4/ds4-%i.env` via `EnvironmentFile=`.

## Enable/Start (Human Runbook)

```bash
sudo systemctl daemon-reload
sudo systemctl enable ds4-preflight@spark0.service
sudo systemctl start  ds4-preflight@spark0.service

sudo systemctl enable ds4@spark0.service
sudo systemctl start  ds4@spark0.service
```

Inspect logs:

```bash
journalctl -u ds4@spark0.service -n 200 --no-pager
journalctl -u ds4-preflight@spark0.service -n 200 --no-pager
```

## Hardening Guidance

`deploy/systemd/ds4@.service` includes conservative sandboxing. Avoid enabling
`MemoryDenyWriteExecute=` until CUDA JIT behavior is fully understood.
