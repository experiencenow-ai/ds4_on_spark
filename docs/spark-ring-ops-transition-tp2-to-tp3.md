# Spark Ring Transition Runbook (TP=2 → TP=3)

This is **human-run** runbook material for expanding a stable Spark0/Spark1 TP=2 baseline into a Spark0/Spark1/Spark2 TP=3 inventory.

Nothing here should be applied automatically. Review any `sudo`/systemd changes on the Sparks before running them.

If you are setting up a fresh 3-node ring from scratch, start with:

- `docs/spark-ring-ops-quickstart-tp3.md`

If Spark0/Spark1 TP=2 readiness is not yet stable, start with:

- `docs/spark-ring-ops-quickstart-tp2.md`
- `docs/spark-ring-ops-readiness-tp2.md`

## Overview

Key idea: use `tp23` (TP=2 + TP=3) snapshots and staged readiness to catch mismatches before installing/enabling anything.

- Mac-side snapshot: `scripts/ops_spark_ring_ops_check.sh --preflight tp23` (mesh + systemd status + optional staged readiness)
- Mac-side staged readiness: `scripts/ops_spark_ring_staged_readiness.sh --preflight tp23` (runs `ops_tp2_readiness.sh` + `ops_tp3_readiness.sh` on each Spark using staged `/tmp/ds4-*` paths)

## 0) Prereqs (Mac Side)

- Decide whether you rely on mDNS (`spark0.local`) or pin `/etc/hosts` (examples: `deploy/config/hosts.ds4.spark012.example`).
- Prefer an ordered inventory file so rank order is explicit and repeatable:
  - `deploy/config/inventory.ds4.spark012.example`

Recommended SSH defaults (dedicated known-hosts file):

```bash
export SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts'
```

Optional (recommended): initialize a private run directory for notes + snapshots:

```bash
RUN_DIR="$(./scripts/ops_run_dir_init.sh --tp tp3 --tag "<tp23-transition-tag>")"
```

## 1) Validate + Stage (Mac Side, Safe)

Validate deploy assets and ops scripts (safe):

```bash
./scripts/ops_validate_deploy_assets.sh
```

Stage templates/config examples/scripts to all 3 hosts (safe; non-destructive):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

Recommended: run staged `tp23` readiness right after staging (safe; no sudo; uses staged `/tmp/ds4-*` assets):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp23 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

Optional (recommended): capture a combined `tp23` snapshot for run notes (safe; read-only):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp23_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp23 --strict --journal --lines 120 \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp23 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

If `tp23` readiness fails, fix the staged env/config first before installing anything. See:

- `docs/ops-tp2-readiness.md`
- `docs/ops-tp3-readiness.md`

## 2) Install + Validate (Spark Side, Human Approval)

On each Spark, review the staged installer wrapper, then install (human-run):

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --start-preflight --preflight tp3
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark1 --start-preflight --preflight tp3
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark2 --start-preflight --preflight tp3
```

Then validate installed assets (safe; recommended before enabling DS4):

```bash
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark0 --strict
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark1 --strict
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark2 --strict
```

## 3) Gate With Strict Preflights (Spark Side, Safe)

Run strict TP=2 preflight on Spark0/Spark1 (safe oneshot):

```bash
sudo systemctl start ds4-preflight-strict@spark0.service
sudo systemctl start ds4-preflight-strict@spark1.service
```

Run strict TP=3 preflight on all three (safe oneshot):

```bash
sudo systemctl start ds4-preflight-tp3-strict@spark0.service
sudo systemctl start ds4-preflight-tp3-strict@spark1.service
sudo systemctl start ds4-preflight-tp3-strict@spark2.service
```

## 4) Start DS4 With TP=3 Gating (Spark Side, Human Approval)

For early bring-up, prefer strict TP=3 gating on start:

```bash
sudo systemctl enable --now ds4-tp3-strict@spark0.service
sudo systemctl enable --now ds4-tp3-strict@spark1.service
sudo systemctl enable --now ds4-tp3-strict@spark2.service
```

## 5) Post-Change Snapshot (Mac Side, Safe)

After install/start changes, capture a fresh `tp23` snapshot for run notes (safe; read-only):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp23_post_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp23 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

## Notes + Runbooks

- Deployment layout: `docs/deployment-spark0-spark1-spark2.md`
- Logging + metrics: `docs/ops-logging-metrics.md`
- SSH + network: `docs/ops-ssh-network-runbook.md`
- TP=3 ports: `docs/ops-spark012-network-ports.md`
- Firewall allowlist guidance (human-run): `docs/ops-firewall-allowlist.md`
- Operating checklist: `docs/spark-ring-ops-checklist-tp3.md`
- Run notes + redaction checklist: `docs/ops-run-notes.md`

