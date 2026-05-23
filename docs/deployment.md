# Deployment

> Supersedes: `docs/deployment-spark012-layout-manifest.md`, `docs/deployment-layout.md`, `docs/deployment-spark012-ops-pack.md`, `docs/deployment-staged-systemd-user.md`, `docs/deployment-spark0-spark1.md`, `docs/deployment-spark-ring.md`, `docs/deployment-systemd.md`, `docs/deployment-spark-standalone-systemd-user.md`, `docs/deployment-spark-standalone-systemd.md`, `docs/deployment-systemd-disable-uninstall.md`, `docs/deployment-spark0-spark1-spark2.md`, `docs/deployment-systemd-user.md`, `docs/deployment-spark012-staged-layout.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 13 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `deployment-spark012-layout-manifest.md`: Deployment: Spark0/Spark1/Spark2 Layout Manifest (Reference) (52 lines).
- `deployment-layout.md`: Deployment Layout (Ordered Spark Inventory) (128 lines).
- `deployment-spark012-ops-pack.md`: Deployment + Ops Index: Spark0/Spark1/Spark2 (TP=2 + TP=3 Prep) (127 lines).
- `deployment-staged-systemd-user.md`: Deployment: Staged `systemd --user` Install (Spark Side, No Sudo) (75 lines).
- `deployment-spark0-spark1.md`: Deployment: Spark0 + Spark1 (TP=2 Prep) (252 lines).
- `deployment-spark-ring.md`: Example Deployment: Spark0..Spark3 (TP=4 Ring Prep) (107 lines).
- `deployment-systemd.md`: Systemd Templates (171 lines).
- `deployment-spark-standalone-systemd-user.md`: Deployment: Spark Standalone via `systemd --user` (Optional) (92 lines).
- `deployment-spark-standalone-systemd.md`: Deployment: Spark Standalone via systemd (Optional) (91 lines).
- `deployment-systemd-disable-uninstall.md`: Systemd Disable / Uninstall (Human Runbook) (172 lines).
- `deployment-spark0-spark1-spark2.md`: Deployment: Spark0 + Spark1 + Spark2 (TP=3 Prep) (143 lines).
- `deployment-systemd-user.md`: Systemd User-Service Templates (Optional) (108 lines).
- `deployment-spark012-staged-layout.md`: Deployment: Spark0/Spark1/Spark2 Staged Layout (TP=3 Prep) (99 lines).

## Command Inventory

- `deployment-spark012-layout-manifest.md`: `./scripts/ops_validate_layout_manifests.sh`
- `deployment-layout.md`: `./scripts/ops_validate_deploy_assets.sh`
- `deployment-layout.md`: `rsync -av deploy/systemd/ <user>@spark0.local:/tmp/ds4-systemd/`
- `deployment-layout.md`: `rsync -av deploy/config/  <user>@spark0.local:/tmp/ds4-config/`
- `deployment-layout.md`: `rsync -av deploy/systemd-dropins/ <user>@spark0.local:/tmp/ds4-systemd-dropins/`
- `deployment-layout.md`: `rsync -av deploy/systemd-user-dropins/ <user>@spark0.local:/tmp/ds4-systemd-user-dropins/`
- `deployment-layout.md`: `rsync -av deploy/sysusers.d/ <user>@spark0.local:/tmp/ds4-sysusers/`
- `deployment-layout.md`: `rsync -av deploy/tmpfiles.d/ <user>@spark0.local:/tmp/ds4-tmpfiles/`
- `deployment-spark012-ops-pack.md`: `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `deployment-spark012-ops-pack.md`: `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp3_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `deployment-spark012-ops-pack.md`: `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp23_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `deployment-spark012-ops-pack.md`: `./scripts/ops_validate_deploy_assets.sh`
- `deployment-spark012-ops-pack.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \`
- `deployment-spark0-spark1.md`: `./scripts/ops_validate_deploy_assets.sh`
- `deployment-spark0-spark1.md`: `./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0`
- `deployment-spark0-spark1.md`: `./scripts/ops_stage_deploy_assets.sh spark1@<spark1-host> spark1`
- `deployment-spark0-spark1.md`: `./scripts/ops_stage_spark0_spark1.sh spark0@<spark0-host> spark1@<spark1-host>`
- `deployment-spark0-spark1.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring --inventory-file deploy/config/inventory.ds4.spark01.example`
- `deployment-spark0-spark1.md`: `./scripts/ops_spark01_mesh_check.sh spark0@<spark0-host> spark1@<spark1-host>`
- `deployment-spark-ring.md`: `./scripts/ops_validate_deploy_assets.sh`
- `deployment-spark-ring.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host> spark3@<spark3-host>`
- `deployment-spark-ring.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring --inventory-file <path-to-your-inventory>`
- `deployment-spark-ring.md`: `DS4_ENV_VARIANT=tp4 ./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2`
- `deployment-systemd.md`: `./scripts/ops_validate_deploy_assets.sh`
- `deployment-systemd.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> [spark2@<spark2-host> ...]`
- `deployment-spark-standalone-systemd-user.md`: `./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0`
- `deployment-spark-standalone-systemd-user.md`: `./scripts/ops_stage_deploy_assets.sh spark1@<spark1-host> spark1`
- `deployment-spark-standalone-systemd-user.md`: `./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2`
- `deployment-spark-standalone-systemd.md`: `./scripts/ops_stage_deploy_assets.sh spark0@<spark0-host> spark0`
- `deployment-spark-standalone-systemd.md`: `./scripts/ops_stage_deploy_assets.sh spark1@<spark1-host> spark1`
- `deployment-spark-standalone-systemd.md`: `./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2`
- `deployment-spark-standalone-systemd.md`: `./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `deployment-systemd-disable-uninstall.md`: `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_post_disable_$(date -u +%Y%m%d-%H%M%SZ).txt" --preflight tp3 --strict --inventory-file deploy/config/inventory.ds4.spark012.example`
- `deployment-spark0-spark1-spark2.md`: `./scripts/ops_validate_deploy_assets.sh`
- `deployment-spark0-spark1-spark2.md`: `./scripts/ops_spark_ring_status.sh --preflight tp3 --strict spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `deployment-spark0-spark1-spark2.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `deployment-spark0-spark1-spark2.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring --inventory-file deploy/config/inventory.ds4.spark012.example`
- `deployment-spark0-spark1-spark2.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \`
- `deployment-spark0-spark1-spark2.md`: `./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp3_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `deployment-spark0-spark1-spark2.md`: `DS4_ENV_VARIANT=tp3 ./scripts/ops_stage_deploy_assets.sh spark2@<spark2-host> spark2`
- `deployment-spark012-staged-layout.md`: `./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --topology ring \`
- `deployment-spark012-staged-layout.md`: `./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --staged-readiness --staged-readiness-strict --topology ring \`
- `deployment-spark012-staged-layout.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring --inventory-file deploy/config/inventory.ds4.spark012.example`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/deployment-spark012-layout-manifest.md` | 52 | Deployment: Spark0/Spark1/Spark2 Layout Manifest (Reference) | Recommended Install Path (Preferred), Manifest Use Cases, Validation (Safe), Safety Notes |
| `docs/deployment-layout.md` | 128 | Deployment Layout (Ordered Spark Inventory) | Topologies, Host Roles (Recommended Convention), Filesystem Layout, Minimal Setup (Human Runbook), Safety Notes |
| `docs/deployment-spark012-ops-pack.md` | 127 | Deployment + Ops Index: Spark0/Spark1/Spark2 (TP=2 + TP=3 Prep) | Pick Your Topology, Safe One-Command Snapshot (Mac Side), Stage → Install → Validate (Repeatable Pattern), Systemd Templates + Overrides, Config + Runbooks |
| `docs/deployment-staged-systemd-user.md` | 75 | Deployment: Staged `systemd --user` Install (Spark Side, No Sudo) | Preconditions (Human Check), Install (Human Run), Validate (Optional, Human Run), Enable + Start (Human Run), Optional: Periodic Preflight Timers (Safe) |
| `docs/deployment-spark0-spark1.md` | 252 | Deployment: Spark0 + Spark1 (TP=2 Prep) | Roles + Naming, On Each Spark: Minimal Filesystem Bring-up, Stage Templates From Your Mac, On Each Spark: Install Systemd + Config, Optional: Validate Installed Assets (Spark Side) |
| `docs/deployment-spark-ring.md` | 107 | Example Deployment: Spark0..Spark3 (TP=4 Ring Prep) | Roles + Naming, Stage Templates From Your Mac, On Each Spark: Install Systemd + Config, TP=4 Preflight (Optional), Conventions + Runbooks |
| `docs/deployment-systemd.md` | 171 | Systemd Templates | Validation Helpers, Units, Instance Naming, Prereqs (Human Runbook), Enable/Start (Human Runbook) |
| `docs/deployment-spark-standalone-systemd-user.md` | 92 | Deployment: Spark Standalone via `systemd --user` (Optional) | What This Provides, Stage Assets From Your Mac, Install (Spark Side, Human Runbook), Logs, Notes |
| `docs/deployment-spark-standalone-systemd.md` | 91 | Deployment: Spark Standalone via systemd (Optional) | What This Provides, Stage Assets From Your Mac, Install (Spark Side, Human Runbook), Logs, Notes |
| `docs/deployment-systemd-disable-uninstall.md` | 172 | Systemd Disable / Uninstall (Human Runbook) | Before You Change Anything (Recommended), System Units (Root / `/etc/systemd/system`), User Units (`systemd --user`) (Optional Path), Post-Checks (Recommended) |
| `docs/deployment-spark0-spark1-spark2.md` | 143 | Deployment: Spark0 + Spark1 + Spark2 (TP=3 Prep) | Roles + Naming, Stage Templates From Your Mac, On Each Spark: Install Systemd + Config, Optional: Developer Path (`systemd --user`, No Sudo), Conventions + Runbooks |
| `docs/deployment-systemd-user.md` | 108 | Systemd User-Service Templates (Optional) | Install (Human Runbook), Unit Overrides (Drop-Ins) (Optional), Run Without Login Sessions (Optional) |
| `docs/deployment-spark012-staged-layout.md` | 99 | Deployment: Spark0/Spark1/Spark2 Staged Layout (TP=3 Prep) | Goals, Mac Side: Stage Assets To All 3 Nodes, Spark Side (System Units): Install + Preflight (Human Approval), Spark Side (`systemd --user`): Install + Preflight (No Sudo), Three-Node Ring Ops Checklist |
