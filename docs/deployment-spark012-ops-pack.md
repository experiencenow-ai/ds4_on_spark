# Deployment + Ops Index: Spark0/Spark1/Spark2 (TP=2 + TP=3 Prep)

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

Goal: one entrypoint that links the deployment layout, systemd templates, config examples, logging/metrics conventions, SSH/network runbooks, operating checklists, and TP=2/TP=3 readiness checks for a 2–3 node Spark inventory.

## Pick Your Topology

- Spark0 + Spark1 (TP=2 baseline):
  - Deployment: `docs/deployment-spark0-spark1.md`
  - Quickstart: `docs/spark-ring-ops-quickstart-tp2.md`
  - Readiness rubric: `docs/spark-ring-ops-readiness-tp2.md`
  - Operating checklist: `docs/spark-ring-ops-checklist-tp2.md`
- Spark0 + Spark1 + Spark2 (TP=3 prep):
  - Deployment: `docs/deployment-spark0-spark1-spark2.md`
  - Quickstart: `docs/spark-ring-ops-quickstart-tp3.md`
  - Readiness rubric: `docs/spark-ring-ops-readiness-tp3.md`
  - Operating checklist: `docs/spark-ring-ops-checklist-tp3.md`

## Safe One-Command Snapshot (Mac Side)

These are read-only checks intended for run notes; they do not modify systemd, networking, or GPU settings.

Optional: initialize a private run directory first (recommended):

```bash
RUN_DIR="$(./scripts/ops_run_dir_init.sh --tp tp3 --tag "<tag>")"
```

TP=2 (two hosts):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp2 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark01.example
```

TP=3 (three hosts):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp3_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp3 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

Snapshots may include hostnames/IPs/routes and journal excerpts; keep outputs private and redact before sharing externally:

- Run-notes conventions + redaction checklist: `docs/ops-run-notes.md`

## Stage → Install → Validate (Repeatable Pattern)

### 1) Validate repo assets (Mac side, safe)

```bash
./scripts/ops_validate_deploy_assets.sh
```

### 2) Stage assets (Mac side, safe; non-destructive)

Prefer inventory-driven staging (ordered inventory defines instance defaults):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

Optional: add staged env audit + staged readiness (safe; runs checks using `/tmp/ds4-*` paths):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \
  --staged-env-audit \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp3 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

### 3) Install staged assets (Spark side, human approval)

Review the wrapper, then install (example for Spark0):

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --start-preflight --preflight tp3
```

Non-root developer bring-up (`systemd --user`) is also supported:

- Runbook: `docs/deployment-systemd-user.md`
- Staged non-root path: `docs/deployment-staged-systemd-user.md`

### 4) Validate installed assets (Spark side, safe)

```bash
sudo /opt/ds4/scripts/ops_validate_installed_assets.sh --instance spark0 --strict
```

## Systemd Templates + Overrides

- Systemd templates: `docs/deployment-systemd.md`
- Optional drop-in override examples (no base-unit edits): `deploy/systemd-dropins/` and `deploy/systemd-user-dropins/`

## Config + Runbooks

- Config examples (env/config, hosts pinning, ssh_config, journald, logrotate, Prometheus): `deploy/config/`
- Logging + metrics conventions: `docs/ops-logging-metrics.md`
- SSH + network runbook (ordered inventory): `docs/ops-ssh-network-runbook.md`
- Ports:
  - TP=2: `docs/ops-spark0-spark1-network-ports.md`
  - TP=3: `docs/ops-spark012-network-ports.md`
- Firewall allowlist guidance (human-run): `docs/ops-firewall-allowlist.md`

## Support Bundles (If Something Looks Wrong)

Non-destructive bundle collector + redaction guidance:

- Runbook: `docs/ops-support-bundle.md`
- Redaction/run-notes: `docs/ops-run-notes.md`
