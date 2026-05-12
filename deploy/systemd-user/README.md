# DS4 Systemd Templates (`systemd --user`)

This directory contains **example** user-service templates intended for `systemd --user` (developer / non-root bring-up).

Nothing here is applied automatically. Prefer staging first (Mac-side), then installing on the Spark with human approval (or with no sudo for user units).

## Install (User Units)

See `docs/deployment-systemd-user.md` for the full runbook.

In brief:

- Copy `ds4*.service` and optional `ds4*.timer` into `~/.config/systemd/user/`
- Keep per-instance config under `~/.config/ds4/`:
  - `ds4.env`
  - `ds4-<instance>.env`
  - `ds4-<instance>.conf`

## Strict Gates (TP Readiness)

Strict “start gates” are provided as separate templates, mirroring the system-unit layout:

- TP=2 strict gate: `ds4-strict@.service` + `ds4-preflight-strict@.service`
- TP=3 strict gate: `ds4-tp3-strict@.service` + `ds4-preflight-tp3-strict@.service`
- TP=4 strict gate: `ds4-tp4-strict@.service` + `ds4-preflight-tp4-strict@.service`

Readiness docs:

- TP=2: `docs/ops-tp2-readiness.md`
- TP=3: `docs/ops-tp3-readiness.md`
- TP=4: `docs/ops-tp4-readiness.md`

