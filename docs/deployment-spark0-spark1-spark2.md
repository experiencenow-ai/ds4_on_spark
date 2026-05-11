# Deployment: Spark0 + Spark1 + Spark2 (TP=3 Prep)

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

Goal: prepare a repeatable Spark0/Spark1/Spark2 layout with staging helpers, systemd templates, consistent logs/metrics, and safe preflight checks for future TP=3 runs.

## Roles + Naming

Recommended convention (matches the templates in `deploy/systemd/`):

- Spark0: rank 0 (`ds4@spark0`)
- Spark1: rank 1 (`ds4@spark1`)
- Spark2: rank 2 (`ds4@spark2`)

The systemd templates set `DS4_INSTANCE=%i` by default and load `/etc/ds4/ds4-%i.env`.

Decide how hosts resolve:

- mDNS (`spark0.local`, `spark1.local`, `spark2.local`) for early bring-up
- pinned `/etc/hosts` entries for stability on an isolated wired subnet (see `deploy/config/hosts.ds4.spark012.example`)

## Stage Templates From Your Mac

Optional (recommended): validate deploy assets + ops scripts before staging:

```bash
./scripts/ops_validate_deploy_assets.sh
```

Recommended (stages all 3 Sparks, avoids instance-name mistakes):

```bash
./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
# optional: add --tcp 29500 --tcp 9090
```

Or stage each host individually:

```bash
./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2
```

Notes:

- Staging is non-destructive; it copies templates + example configs to `/tmp/` on each Spark.
- `--mesh-check` runs a best-effort reachability check first (`scripts/ops_spark012_mesh_check.sh`).
- For stable host key handling, set `SSH_OPTS` to use a dedicated known-hosts file (or use `deploy/config/ssh_config.ds4.spark012.example`).

## On Each Spark: Install Systemd + Config

Recommended: use the staged installer wrapper (human-run; review first):

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance <spark0|spark1|spark2> --start-preflight
```

Notes:

- By default the installer is idempotent and does **not** overwrite existing `/etc/ds4/ds4-*.env` or `ds4-*.conf`. Use `--overwrite-config` only if you intentionally want to replace an existing env/config file.
- `deploy/config/ds4-spark0.env.example` / `ds4-spark1.env.example` default to TP=2; for TP=3, set `DS4_WORLD_SIZE=3` and assign `DS4_RANK=0/1/2` in the per-instance env files.
- For TP=3, prefer a rank-ordered host list in the env file (example):
  `DS4_RING_HOSTS=spark0.local,spark1.local,spark2.local`

## Conventions + Runbooks

- Deployment/systemd templates: `docs/deployment-systemd.md`
- Logging + metrics: `docs/ops-logging-metrics.md`
- SSH + network: `docs/ops-ssh-network-runbook.md`
- TP=3 network + ports: `docs/ops-spark012-network-ports.md`

