# Ops

> Supersedes: `docs/ops-prometheus-alerting.md`, `docs/ops-sysctl-network-tuning.md`, `docs/ops-logging-metrics.md`, `docs/ops-spark012-network-ports.md`, `docs/ops-run-notes.md`, `docs/ops-spark-ring-network-ports.md`, `docs/ops-support-bundle.md`, `docs/ops-spark0-spark1-network-ports.md`, `docs/ops-deploy-asset-validation.md`, `docs/ops-firewall-routing-inspection.md`, `docs/ops-centaur-operational-hooks.md`, `docs/ops-firewall-allowlist.md`, `docs/ops-ssh-network-runbook.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 13 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `ops-prometheus-alerting.md`: Ops: Prometheus Alerting (DS4) (51 lines).
- `ops-sysctl-network-tuning.md`: Ops: Optional sysctl network tuning (Spark0/Spark1) (52 lines).
- `ops-logging-metrics.md`: Ops: Logging + Metrics Conventions (83 lines).
- `ops-spark012-network-ports.md`: Ops: Spark0/Spark1/Spark2 Network + Ports (TP=3 Prep) (58 lines).
- `ops-run-notes.md`: Ops: Run Notes + Snapshot Hygiene (109 lines).
- `ops-spark-ring-network-ports.md`: Example Ops: Spark Ring Network + Ports (Spark0..Spark3) (61 lines).
- `ops-support-bundle.md`: Ops: DS4 Support Bundle (Safe) (82 lines).
- `ops-spark0-spark1-network-ports.md`: Ops: Spark0/Spark1 Network + Ports (TP=2 Prep) (61 lines).
- `ops-deploy-asset-validation.md`: Ops: Deploy Asset Validation (Safe) (58 lines).
- `ops-firewall-routing-inspection.md`: Ops: Firewall + Routing Inspection (Read-only) (87 lines).
- `ops-centaur-operational-hooks.md`: Ops: Centaur Operational Hooks (Deployment/Runbook Only) (125 lines).
- `ops-firewall-allowlist.md`: Ops: Firewall Allowlist Examples (Human-run) (84 lines).
- `ops-ssh-network-runbook.md`: Ops: SSH + Network Runbook (Ordered Spark Inventory) (226 lines).

## Command Inventory

- `ops-spark012-network-ports.md`: `curl -fsS "http://127.0.0.1:${DS4_METRICS_PORT}/metrics" | head`
- `ops-run-notes.md`: `./scripts/ops_spark_ring_ops_check.sh --out "$RUN_DIR/ops_check_pre.txt" \`
- `ops-run-notes.md`: `./scripts/ops_spark_ring_ops_check.sh --out "$RUN_DIR/ops_check_staged_ready.txt" \`
- `ops-spark-ring-network-ports.md`: `curl -fsS "http://127.0.0.1:${DS4_METRICS_PORT}/metrics" | head`
- `ops-support-bundle.md`: `./scripts/ops_collect_support_bundle.sh --instance spark0 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env`
- `ops-spark0-spark1-network-ports.md`: `curl -fsS "http://127.0.0.1:${DS4_METRICS_PORT}/metrics" | head`
- `ops-spark0-spark1-network-ports.md`: `ssh -o BatchMode=yes <peer-user>@<peer-host> hostname`
- `ops-spark0-spark1-network-ports.md`: `ssh $SSH_OPTS spark0@<spark0-host> hostname`
- `ops-deploy-asset-validation.md`: `./scripts/ops_validate_deploy_assets.sh`
- `ops-centaur-operational-hooks.md`: `./scripts/centaur_spark_v73_stage.sh spark1@<spark1-host> "~/centaur-smoke/v73"`
- `ops-centaur-operational-hooks.md`: `./scripts/centaur_spark_v73_stage.sh spark2@<spark2-host> "~/centaur-smoke/v73"`
- `ops-centaur-operational-hooks.md`: `./scripts/centaur_spark_v73_node_setup_run.sh spark1@<spark1-host> "~/centaur-smoke/v73"`
- `ops-centaur-operational-hooks.md`: `./scripts/centaur_spark_v73_node_setup_run.sh spark2@<spark2-host> "~/centaur-smoke/v73"`
- `ops-centaur-operational-hooks.md`: `./scripts/centaur_spark_v73_node_setup_run.sh spark2@<spark2-host> "~/centaur-smoke/v73" "" /private/tmp/centaur_node_setup_spark2.log`
- `ops-centaur-operational-hooks.md`: `./scripts/centaur_spark_ring_rsync_v73.sh spark1@<spark1-host> spark2@<spark2-host>`
- `ops-centaur-operational-hooks.md`: `./scripts/ops_spark_rsync_check.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `ops-firewall-allowlist.md`: `ssh -o BatchMode=yes -o ConnectTimeout=10 spark0@<spark0-host> hostname`
- `ops-firewall-allowlist.md`: `curl -fsS "http://<spark2-host>:${DS4_METRICS_PORT}/metrics" | head`
- `ops-ssh-network-runbook.md`: `ssh $SSH_OPTS <user>@spark0.local hostname`
- `ops-ssh-network-runbook.md`: `ssh -F /private/tmp/ds4_ssh_config spark0@<spark0-host> hostname`
- `ops-ssh-network-runbook.md`: `ssh-keygen -F spark0.local -f "$KH" || true`
- `ops-ssh-network-runbook.md`: `ssh-keygen -R spark0.local -f "$KH" || true`
- `ops-ssh-network-runbook.md`: `ssh -G $SSH_OPTS spark0@<spark0-host> 2>/dev/null | grep -E '^(userknownhostsfile|stricthostkeychecking|identityfile|batchmode) ' || true`
- `ops-ssh-network-runbook.md`: `./scripts/ops_spark01_mesh_check.sh spark0@<spark0-host> spark1@<spark1-host>`
- `ops-ssh-network-runbook.md`: `./scripts/ops_stage_spark0_spark1.sh --mesh-check spark0@<spark0-host> spark1@<spark1-host>`
- `ops-ssh-network-runbook.md`: `./scripts/ops_spark_ring_mesh_check.sh --topology ring spark0@<spark0-host> spark1@<spark1-host> [spark2@<spark2-host> ...]`
- `ops-ssh-network-runbook.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring spark0@<spark0-host> spark1@<spark1-host> [spark2@<spark2-host> ...]`
- `ops-ssh-network-runbook.md`: `./scripts/ops_spark_ring_mesh_check.sh --topology ring --inventory-file <path-to-inventory>`
- `ops-ssh-network-runbook.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring --inventory-file <path-to-inventory>`
- `ops-ssh-network-runbook.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --staged-readiness --staged-readiness-strict --topology ring \`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/ops-prometheus-alerting.md` | 51 | Ops: Prometheus Alerting (DS4) | Inputs From This Repo, Label Conventions, Load Rules (Example), Testing (Safe) |
| `docs/ops-sysctl-network-tuning.md` | 52 | Ops: Optional sysctl network tuning (Spark0/Spark1) | When To Consider, Inspect (Read-only), Apply (Optional; Human-run), Roll Back (Human-run), Risks |
| `docs/ops-logging-metrics.md` | 83 | Ops: Logging + Metrics Conventions | Logging, Metrics, Spark (Optional) |
| `docs/ops-spark012-network-ports.md` | 58 | Ops: Spark0/Spark1/Spark2 Network + Ports (TP=3 Prep) | Hostnames + Paths, Ports (Defaults), Safe Checks (Spark Side), Firewall + Routing Inspection (Read-only) |
| `docs/ops-run-notes.md` | 109 | Ops: Run Notes + Snapshot Hygiene | Recommended Run Directory (Mac Side), What To Capture (Baseline), Summary, Code + Build, Config |
| `docs/ops-spark-ring-network-ports.md` | 61 | Example Ops: Spark Ring Network + Ports (Spark0..Spark3) | Hostnames + Paths, Ports (Defaults), Safe Checks (Spark Side), Firewall + Routing Inspection (Read-only) |
| `docs/ops-support-bundle.md` | 82 | Ops: DS4 Support Bundle (Safe) | Run (Spark Side), What It Captures, Redaction Guidance |
| `docs/ops-spark0-spark1-network-ports.md` | 61 | Ops: Spark0/Spark1 Network + Ports (TP=2 Prep) | Hostnames + Paths, Ports (Defaults), Safe Checks (Spark Side), Firewall + Routing Inspection (Read-only), Safe Checks (Mac Side) |
| `docs/ops-deploy-asset-validation.md` | 58 | Ops: Deploy Asset Validation (Safe) | Run (Mac Side), Run (Spark Side), What It Checks, When To Use It |
| `docs/ops-firewall-routing-inspection.md` | 87 | Ops: Firewall + Routing Inspection (Read-only) | Routing + Interface (Spark Side), Name Resolution (Spark Side), Firewall State (Spark Side, Read-only), What To Record |
| `docs/ops-centaur-operational-hooks.md` | 125 | Ops: Centaur Operational Hooks (Deployment/Runbook Only) | What’s In This Repo, Safety / Expectations, Inputs, Stage To A Spark (Mac Side), Setup On A Spark (Mac Wrapper) |
| `docs/ops-firewall-allowlist.md` | 84 | Ops: Firewall Allowlist Examples (Human-run) | Goals, Ports (Defaults), Read-only Inspection First, Example: nftables Snippet (TP=3 / Spark0-Spark2), Validation After Applying (Human-run) |
| `docs/ops-ssh-network-runbook.md` | 226 | Ops: SSH + Network Runbook (Ordered Spark Inventory) | SSH Identity, Known-Hosts Hygiene (Mac Side), Mac-Side Mesh Check (Optional), Mac-Side Systemd Status Snapshot (Optional), Peer SSH From DS4 Preflight (Optional) |
