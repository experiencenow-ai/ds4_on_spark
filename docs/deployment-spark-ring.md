# Example Deployment: Spark0..Spark3 (TP=4 Ring Prep)

Prefer inventory-driven staging for new work:

- `scripts/ops_stage_spark_ring.sh <spark0> <spark1> [spark2 ...]`
- `scripts/ops_spark_ring_mesh_check.sh <spark0> <spark1> [spark2 ...]`

The current 3-node example remains `docs/deployment-spark0-spark1-spark2.md`. This file is retained as a 4-node/TP=4 example, not as a source of truth for the active inventory.

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

Goal: prepare a repeatable Spark0/Spark1/Spark2/Spark3 layout with systemd templates, consistent logs/metrics, and safe preflight checks for future TP=4 runs.

## Roles + Naming

Recommended convention (matches the templates in `deploy/systemd/`):

- Spark0: rank 0 (`ds4@spark0`)
- Spark1: rank 1 (`ds4@spark1`)
- Spark2: rank 2 (`ds4@spark2`)
- Spark3: rank 3 (`ds4@spark3`)

The systemd templates set `DS4_INSTANCE=%i` by default and load `/etc/ds4/ds4-%i.env`.

## Stage Templates From Your Mac

Optional (recommended): validate deploy assets + ops scripts before staging:

```bash
./scripts/ops_validate_deploy_assets.sh
```

Recommended (stages all 4 Sparks, avoids instance-name mistakes):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host> spark3@<spark3-host>
# optional: add --tcp 29500 --tcp 9090
```

Optional: keep the ordered inventory in a file (any newline-delimited list of `<user>@<host>` works; see `deploy/config/inventory.ds4.spark_ring.example` for the format):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring --inventory-file <path-to-your-inventory>
```
At the end of staging, the helper runs a safe staged env audit to catch common ring mismatches before install:

- `scripts/ops_spark_ring_staged_env_audit.sh` (reads `/tmp/ds4-config/ds4-<instance>.env.example` on each Spark)

Or stage each host individually:

```bash
DS4_ENV_VARIANT=tp4 ./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2
```

## On Each Spark: Install Systemd + Config

Recommended: use the staged installer wrapper (human-run; review first):

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance <spark0|spark1|spark2|spark3> --start-preflight --preflight tp4
```

Notes:

- By default the installer is idempotent and does **not** overwrite existing `/etc/ds4/ds4-*.env` or `ds4-*.conf`. Use `--overwrite-config` only if you intentionally want to replace an existing env/config file.
- `scripts/ops_stage_spark_ring.sh` stages TP=4 env variants by default (`deploy/config/ds4-spark*.tp4.env.example`) by setting `DS4_ENV_VARIANT=tp4` per host during staging.
- If you stage hosts manually, set `DS4_ENV_VARIANT=tp4` to swap `ds4-<instance>.tp4.env.example` into `ds4-<instance>.env.example` on the Spark (see `deploy/README.md`).

## TP=4 Preflight (Optional)

This repo provides TP=4-specific systemd oneshots:

- `ds4-preflight-tp4@.service`
- `ds4-preflight-tp4-strict@.service`

Example (human-run):

```bash
sudo systemctl daemon-reload
sudo systemctl start ds4-preflight-tp4@spark0.service
sudo systemctl start ds4-preflight-tp4@spark1.service
sudo systemctl start ds4-preflight-tp4@spark2.service
sudo systemctl start ds4-preflight-tp4@spark3.service
```

Strict gating (fails non-zero if required TP=4 inputs are missing/invalid; triggers `ds4-support-bundle@%i.service` on failure when installed):

```bash
sudo systemctl start ds4-preflight-tp4-strict@spark0.service
```

Details: `docs/ops-tp4-readiness.md`.

If you want strict TP=4 gating on start (recommended for early ring bring-up), enable the topology-specific strict unit:

```bash
sudo systemctl enable ds4-tp4-strict@spark0.service
sudo systemctl start  ds4-tp4-strict@spark0.service
```

## Conventions + Runbooks

- Deployment/systemd templates: `docs/deployment-systemd.md`
- Logging + metrics: `docs/ops-logging-metrics.md`
- SSH + network: `docs/ops-ssh-network-runbook.md`
- Ring network + ports: `docs/ops-spark-ring-network-ports.md`
- Four-node operating checklist: `docs/spark-ring-ops-checklist.md`
