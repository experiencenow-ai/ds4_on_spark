# Spark Ring Ops Readiness (Spark0/Spark1 / TP=2 Baseline)

This document defines a **glanceable** readiness rubric for a 2-node baseline (Spark0 + Spark1).

It is intended for **human-run** ops. Nothing here should be applied automatically.

Use this alongside:

- Quickstart: `docs/spark-ring-ops-quickstart-tp2.md`
- Operating checklist: `docs/spark-ring-ops-checklist-tp2.md`
- SSH + network runbook: `docs/ops-ssh-network-runbook.md`
- TP=2 readiness checks: `docs/ops-tp2-readiness.md`
- Ports: `docs/ops-spark0-spark1-network-ports.md`

## One Command Snapshot (Mac Side, Safe)

To capture a single “are we ready?” snapshot (mesh + systemd status) across the ordered inventory:

```bash
./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp2 --strict --journal --lines 120 \
  spark0@<spark0-host> spark1@<spark1-host>
```

Or using an inventory file (recommended for repeatable runs):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp2 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark01.example
```

Note: snapshots may include hostnames/IPs/routes and journal excerpts; keep the output private and redact before sharing externally.

This is read-only. It does not start/stop services or modify networking.

If you already staged deploy assets to `/tmp/ds4-*` on both Sparks, you can also include staged readiness checks in the same snapshot (safe; no sudo):

```bash
./scripts/ops_spark_ring_ops_check.sh --preflight tp2 --strict --journal --lines 120 \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp2 \
  --inventory-file deploy/config/inventory.ds4.spark01.example
```

## Readiness Rubric (TP=2)

Mark each item as:

- **READY**: checked and OK
- **WARN**: checked but not ideal (document impact)
- **BLOCKED**: not OK; do not proceed

### Inventory + SSH (Mac Side)

- **READY**: `SSH_OPTS` uses key auth + a dedicated known-hosts file and both inventory targets are reachable.
- **BLOCKED**: either host is intermittently unreachable or host keys are flapping.

Runbook: `docs/ops-ssh-network-runbook.md`.

### Name Resolution + Routing (Spark Side)

- **READY**: each host resolves its peer consistently (mDNS or pinned `/etc/hosts`), and `ip route get <peer>` shows the intended interface.
- **WARN**: mixed wired/Wi‑Fi paths (record what’s in use).
- **BLOCKED**: routing is inconsistent or peer resolution fails.

Inspection guidance: `docs/ops-firewall-routing-inspection.md`.

### Ports + Metrics Reachability (Best-Effort)

- **READY**: the chosen DS4 master port is reachable peer-to-peer (example: `29500`) and metrics endpoints are reachable (example: `9090`).
- **WARN**: metrics missing (acceptable for early bring-up if documented).
- **BLOCKED**: master port is not reachable between hosts.

Ports: `docs/ops-spark0-spark1-network-ports.md`.

### Env Consistency (TP=2 Inputs)

For each host’s env (`/etc/ds4/ds4-<instance>.env` or user equivalent):

- **READY**: `DS4_WORLD_SIZE=2`, `DS4_RANK=0/1`, and a valid `DS4_MASTER_ADDR`/`DS4_MASTER_PORT` are present and consistent.
- **READY**: Spark0 has a correct `DS4_PEER_HOST` (Spark1’s address) for reachability checks.
- **BLOCKED**: master/peer settings are missing, ambiguous (wildcard/loopback), or inconsistent between hosts.

Docs: `docs/ops-tp2-readiness.md`.

### Systemd Templates + Preflight (Strict Gate)

- **READY**: the strict TP=2 preflight unit exists and succeeds on both hosts:
  - `ds4-preflight-strict@<instance>.service`
- **WARN**: non-strict preflight passes but strict fails (investigate; document).
- **BLOCKED**: strict preflight fails or templates/scripts are missing.

Docs: `docs/deployment-systemd.md`, `docs/ops-tp2-readiness.md`.

### Logs + Support Bundle Hook

- **READY**: instance logs are visible in journald and a support bundle can be collected without destructive steps.
- **WARN**: logs exist but are hard to filter (fix tags/units before soak tests).
- **BLOCKED**: no logs, or support bundle script is missing.

Docs: `docs/ops-logging-metrics.md`, `docs/ops-support-bundle.md`.

## TP=2 / TP=3 Readiness Notes (Future-Proofing)

TP=2 strict preflight is still useful even when targeting TP=3:

- First, run TP=2 strict preflight on Spark0/Spark1 to validate peer/master routing assumptions.
- Then, run TP=3 strict preflight on Spark0/Spark1/Spark2 to validate rank + ring host list.

Do not change firewall rules, routing, or system services as part of automation loops; document proposed changes for human approval.

