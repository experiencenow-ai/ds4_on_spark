# DS4 Systemd Templates (System Units)

This directory contains **example** systemd unit templates intended for `/etc/systemd/system/` on a Spark host.

Nothing here is applied automatically. Prefer staging first (Mac-side), then installing on the Spark with human approval.

## Staging + Install (Recommended)

- Stage deploy assets from the Mac: `scripts/ops_stage_spark_ring.sh` (or `scripts/ops_stage_deploy_assets.sh`)
- On the Spark, review then run: `/tmp/ds4-scripts/ops_install_staged_assets.sh`

Docs:

- Systemd overview: `docs/deployment-systemd.md`
- Spark0/Spark1/Spark2 layout: `docs/deployment-spark0-spark1-spark2.md`
- Staged layout: `docs/deployment-spark012-staged-layout.md`

## Instance Naming

Templates are instance-based (`%i`). Recommended instances match host roles:

- `spark0`, `spark1`, `spark2` (and `spark3` when present)

The templates load:

- optional shared defaults: `/etc/ds4/ds4.env`
- per-instance env: `/etc/ds4/ds4-%i.env`
- per-instance config: `/etc/ds4/ds4-%i.conf`

## Strict Gates (TP Readiness)

Strict “start gates” are provided as separate templates:

- TP=2 strict gate: `ds4-strict@.service` + `ds4-preflight-strict@.service`
- TP=3 strict gate: `ds4-tp3-strict@.service` + `ds4-preflight-tp3-strict@.service`
- TP=4 strict gate: `ds4-tp4-strict@.service` + `ds4-preflight-tp4-strict@.service`

Readiness docs:

- TP=2: `docs/ops-tp2-readiness.md`
- TP=3: `docs/ops-tp3-readiness.md`
- TP=4: `docs/ops-tp4-readiness.md`

