# Ops: Run Notes + Snapshot Hygiene

Goal: make Spark runs reproducible, debuggable, and shareable **without leaking private host/network details**.

This repo provides safe Mac-side snapshot helpers (mesh + systemd + optional journald tail) and Spark-side support bundles. Use them, but treat the outputs as **sensitive** by default.

## Recommended Run Directory (Mac Side)

Snapshots and run logs often include hostnames, IPs/routes, unit names, and journald excerpts. Create a private run directory with restrictive permissions:

```bash
umask 077
RUN_DIR="${HOME}/ds4_run_logs/$(date -u +%Y%m%d-%H%M%SZ)_tp3_<tag>"
mkdir -p "$RUN_DIR"
```

Notes:

- Prefer a directory under your home folder (persists across reboots) vs `/private/tmp` (ephemeral).
- If you do use `/private/tmp`, keep it private and copy out anything you want to keep.

## What To Capture (Baseline)

### 1) A Mac-Side Snapshot (Safe)

Capture a single snapshot before and after staging/starting DS4:

```bash
./scripts/ops_spark_ring_ops_check.sh --out "$RUN_DIR/ops_check_pre.txt" \
  --preflight tp3 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

If you already staged assets and want to include staged readiness checks (safe; uses `/tmp/ds4-*`):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "$RUN_DIR/ops_check_staged_ready.txt" \
  --preflight tp3 --strict --journal --lines 120 \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp3 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

### 2) A Run Notes File

Keep a short `run.md` alongside snapshots with the facts you’ll need later:

```bash
cat >"$RUN_DIR/run.md" <<'EOF'
# DS4 Run Notes

## Summary
- Topology: TP=? (nodes=?)
- Inventory: (spark0/spark1/spark2 hostnames)
- Goal: (what you were trying)

## Code + Build
- Repo: experiencenow-ai/ds4_on_spark
- Git SHA: (git rev-parse HEAD)
- Build mode: (release/debug, compiler, CUDA, etc.)

## Config
- DS4_WORLD_SIZE=
- DS4_RANK per host: spark0=, spark1=, spark2=
- DS4_RING_HOSTS=
- Interface path: wired vs Wi‑Fi (record if relevant)

## Commands
- Mac-side: ops helpers invoked + flags
- Spark-side: systemd actions taken (enable/start/stop)

## Artifacts
- ops snapshot(s): ops_check_*.txt
- support bundle(s): support_bundle_*.tar.gz (if any)
EOF
```

Tip: record the `--out` file paths in `run.md` so you can find them later.

### 3) Support Bundles (When Something Fails)

Prefer collecting a non-destructive bundle early, then deciding what to share:

- `docs/ops-support-bundle.md`

## Sharing + Redaction (Required For External Sharing)

Before posting any snapshot/support-bundle contents outside your private ops channel:

- Remove/replace hostnames, IPs, MACs, and routes.
- Remove identity paths (e.g. `IdentityFile`), usernames, and any tokens/keys.
- Remove any `curl` endpoints that encode internal topology or credentials.
- Prefer sharing **the smallest excerpt** that explains the issue, not the full file.

If you are unsure, treat the file as confidential and ask for a redaction review.

## Related Docs

- SSH + network: `docs/ops-ssh-network-runbook.md`
- Logging + metrics: `docs/ops-logging-metrics.md`
- Three-node checklist: `docs/spark-ring-ops-checklist-tp3.md`
- TP readiness: `docs/ops-tp2-readiness.md`, `docs/ops-tp3-readiness.md`, `docs/ops-tp4-readiness.md`

