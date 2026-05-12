# Spark Ring Ops Readiness (Spark0/Spark1/Spark2 / TP=3)

This document defines a **glanceable** readiness rubric for a 3-node ring (Spark0/Spark1/Spark2).

It is intended for **human-run** ops. Nothing here should be applied automatically.

Use this alongside:

- Quickstart: `docs/spark-ring-ops-quickstart-tp3.md`
- Operating checklist: `docs/spark-ring-ops-checklist-tp3.md`
- SSH + network runbook: `docs/ops-ssh-network-runbook.md`
- TP=3 readiness checks: `docs/ops-tp3-readiness.md`

## One Command Snapshot (Mac Side, Safe)

To capture a single “are we ready?” snapshot (mesh + systemd status) across the ordered inventory:

```bash
./scripts/ops_spark_ring_ops_check.sh --preflight tp3 --strict --journal --lines 120 \
  spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

Or using an inventory file (recommended for repeatable runs):

```bash
./scripts/ops_spark_ring_ops_check.sh --preflight tp3 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

This is read-only. It does not start/stop services or modify networking.

## Readiness Rubric (TP=3)

Mark each item as:

- **READY**: checked and OK
- **WARN**: checked but not ideal (document impact)
- **BLOCKED**: not OK; do not proceed

### Inventory + SSH (Mac Side)

- **READY**: `SSH_OPTS` uses key auth + a dedicated known-hosts file and all inventory targets are reachable.
- **BLOCKED**: any host is intermittently unreachable or host keys are flapping.

Runbook: `docs/ops-ssh-network-runbook.md`.

### Name Resolution + Routing (Spark Side)

- **READY**: each host resolves every peer consistently (mDNS or pinned `/etc/hosts`), and `ip route get <peer>` shows the intended interface.
- **WARN**: mixed wired/Wi‑Fi paths (record what’s in use).
- **BLOCKED**: routing is inconsistent or peer resolution fails.

Inspection guidance: `docs/ops-firewall-routing-inspection.md`.

### Ports + Metrics Reachability (Best-Effort)

- **READY**: the chosen DS4 master port is reachable peer-to-peer (example: `29500`) and metrics endpoints are reachable (example: `9090`).
- **WARN**: metrics missing (acceptable for early bring-up if documented).
- **BLOCKED**: master port is not reachable between hosts.

Ports: `docs/ops-spark012-network-ports.md`.

### Env Consistency (TP=3 Inputs)

For each host’s env (`/etc/ds4/ds4-<instance>.env` or user equivalent):

- **READY**: `DS4_WORLD_SIZE=3`, `DS4_RANK=0/1/2`, and a rank-ordered `DS4_RING_HOSTS` list is present and consistent across all hosts.
- **BLOCKED**: any mismatch in `DS4_RING_HOSTS`, duplicate ranks, or world-size mismatch.

If you staged assets, you can audit staged env consistency (safe):

```bash
./scripts/ops_spark_ring_staged_env_audit.sh spark0@... spark1@... spark2@...
```

### Systemd Templates + Preflight (Strict Gate)

- **READY**: the strict TP=3 preflight unit exists and succeeds on all hosts:
  - `ds4-preflight-tp3-strict@<instance>.service`
- **WARN**: non-strict preflight passes but strict fails (investigate; document).
- **BLOCKED**: strict preflight fails or templates/scripts are missing.

Docs: `docs/deployment-systemd.md`, `docs/ops-tp3-readiness.md`.

### Logs + Support Bundle Hook

- **READY**: instance logs are visible in journald and a support bundle can be collected without destructive steps.
- **WARN**: logs exist but are hard to filter (fix tags/units before soak tests).
- **BLOCKED**: no logs, or support bundle script is missing.

Docs: `docs/ops-logging-metrics.md`, `docs/ops-support-bundle.md`.

## TP=2 / TP=3 Readiness Notes (Future-Proofing)

TP=2 readiness (Spark0/Spark1) is still useful as a baseline even when targeting TP=3:

- Run TP=2 strict preflight on Spark0 and Spark1 to validate peer/master routing assumptions.
- Then run TP=3 strict preflight on all three hosts to validate rank + ring host list.

Do not change firewall rules, routing, or system services as part of automation loops; document proposed changes for human approval.

