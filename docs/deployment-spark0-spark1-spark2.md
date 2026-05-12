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

Recommended (ordered inventory; this example stages three Sparks):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
# optional: add --tcp 29500 --tcp 9090
```

Or stage each host individually:

```bash
DS4_ENV_VARIANT=tp3 ./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2
```

Notes:

- Staging is non-destructive; it copies templates + example configs to `/tmp/` on each Spark.
- `--mesh-check` runs a best-effort reachability check first (`scripts/ops_spark_ring_mesh_check.sh`).
- For stable host key handling, set `SSH_OPTS` to use a dedicated known-hosts file (or use `deploy/config/ssh_config.ds4.spark012.example`).

## On Each Spark: Install Systemd + Config

Recommended: use the staged installer wrapper (human-run; review first):

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance <spark0|spark1|spark2> --start-preflight --preflight tp3
```

Notes:

- By default the installer is idempotent and does **not** overwrite existing `/etc/ds4/ds4-*.env` or `ds4-*.conf`. Use `--overwrite-config` only if you intentionally want to replace an existing env/config file.
- `scripts/ops_stage_spark0_spark1_spark2.sh` stages TP=3 env variants by default (`deploy/config/ds4-spark*.tp3.env.example`) by setting `DS4_ENV_VARIANT=tp3` per host during staging.
- If you stage hosts manually, set `DS4_ENV_VARIANT=tp3` to swap `ds4-<instance>.tp3.env.example` into `ds4-<instance>.env.example` on the Spark (see `deploy/README.md`).
- For TP=3, prefer a rank-ordered host list in the env file (example):
  `DS4_RING_HOSTS=spark0.local,spark1.local,spark2.local`

If you want strict TP=3 gating on start (recommended for early bring-up), enable the topology-specific strict unit:

```bash
sudo systemctl enable ds4-tp3-strict@spark0.service
sudo systemctl start  ds4-tp3-strict@spark0.service
```

## Conventions + Runbooks

- Deployment/systemd templates: `docs/deployment-systemd.md`
- Logging + metrics: `docs/ops-logging-metrics.md`
- SSH + network: `docs/ops-ssh-network-runbook.md`
- TP=3 network + ports: `docs/ops-spark012-network-ports.md`
- TP=3 readiness checks: `docs/ops-tp3-readiness.md`
- Three-node operating checklist: `docs/spark-ring-ops-checklist-tp3.md`
