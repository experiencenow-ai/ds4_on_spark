# Ops Tp

> Supersedes: `docs/ops-tp23-readiness.md`, `docs/ops-tp2-readiness.md`, `docs/ops-tp3-readiness.md`, `docs/ops-tp4-readiness.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 4 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `ops-tp23-readiness.md`: Ops: TP=2 + TP=3 Readiness Checks (Safe, Transition Helper) (76 lines).
- `ops-tp2-readiness.md`: Ops: TP=2 Readiness Checks (Safe) (229 lines).
- `ops-tp3-readiness.md`: Ops: TP=3 Readiness Checks (Safe) (122 lines).
- `ops-tp4-readiness.md`: Example Ops: TP=4 Readiness Checks (Safe) (91 lines).

## Command Inventory

- `ops-tp23-readiness.md`: `./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp23_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `ops-tp23-readiness.md`: `./scripts/ops_spark_ring_ops_check.sh --preflight tp23 --strict --journal --lines 120 \`
- `ops-tp2-readiness.md`: `./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \`
- `ops-tp2-readiness.md`: `./scripts/ops_spark_ring_ops_check.sh --preflight tp2 --strict --journal --lines 120 \`
- `ops-tp2-readiness.md`: `ssh -o BatchMode=yes <peer-user>@<peer-host> hostname`
- `ops-tp3-readiness.md`: `DS4_RING_HOSTS=spark0.local,spark1.local,spark2.local`
- `ops-tp3-readiness.md`: `./scripts/ops_stage_spark_ring.sh --mesh-check --staged-readiness --staged-readiness-strict --topology ring \`
- `ops-tp3-readiness.md`: `./scripts/ops_spark_ring_staged_readiness.sh --preflight tp3 --strict --topology ring \`
- `ops-tp3-readiness.md`: `./scripts/ops_spark_ring_staged_readiness.sh --preflight tp23 --strict --topology ring \`
- `ops-tp4-readiness.md`: `DS4_RING_HOSTS=spark0.local,spark1.local,spark2.local,spark3.local`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/ops-tp23-readiness.md` | 76 | Ops: TP=2 + TP=3 Readiness Checks (Safe, Transition Helper) | One Command Snapshot (Mac Side, Safe), Commands (Spark Side, Safe), Systemd Hook (Optional) |
| `docs/ops-tp2-readiness.md` | 229 | Ops: TP=2 Readiness Checks (Safe) | Preflight Checklist, One Command Snapshot (Mac Side, Safe), Commands (Spark Side), Inter-Spark Connectivity, NCCL Smoke Test (Optional) |
| `docs/ops-tp3-readiness.md` | 122 | Ops: TP=3 Readiness Checks (Safe) | Ring Host List, Commands (Mac Side, Staged Assets), Commands (Spark Side), Systemd Hook (Optional), Optional: Periodic TP=3 Preflight (Systemd Timer) |
| `docs/ops-tp4-readiness.md` | 91 | Example Ops: TP=4 Readiness Checks (Safe) | Ring Host List, Commands (Spark Side), Systemd Hook (Optional), Optional: Periodic TP=4 Preflight (Systemd Timer) |
