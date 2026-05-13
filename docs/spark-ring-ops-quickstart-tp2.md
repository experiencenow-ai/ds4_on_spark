# Spark Ring Ops Quickstart (Spark0/Spark1 / TP=2 Baseline)

This is a **human-run** quickstart for a 2-node baseline (Spark0 + Spark1) that you can use before expanding to a 3-node ring (TP=3).

Nothing here should be applied automatically. Review any `sudo`/systemd changes on the Sparks before running them.

Use this alongside:

- Deployment layout: `docs/deployment-spark0-spark1.md`
- SSH + network runbook: `docs/ops-ssh-network-runbook.md`
- Logging + metrics conventions: `docs/ops-logging-metrics.md`
- Operating checklist: `docs/spark-ring-ops-checklist-tp2.md`
- Readiness rubric: `docs/spark-ring-ops-readiness-tp2.md`
- TP=2 readiness checks: `docs/ops-tp2-readiness.md`

## 0) Choose Names + Inventory (Mac Side)

- Decide whether you rely on mDNS (`spark0.local`) or pin `/etc/hosts` (examples: `deploy/config/hosts.ds4.spark01.example`).
- Prefer an ordered inventory file so Spark0/Spark1 roles are explicit and repeatable:
  - `deploy/config/inventory.ds4.spark01.example`

Recommended Mac-side SSH defaults (dedicated known-hosts file):

```bash
export SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts'
```

## 1) Stage Deploy Assets + Scripts (Mac Side, Safe)

Validate the repo’s deploy assets and ops scripts (safe):

```bash
./scripts/ops_validate_deploy_assets.sh
```

Stage templates/config examples/scripts to Spark0 + Spark1 (safe; non-destructive):

```bash
./scripts/ops_stage_spark0_spark1.sh --mesh-check spark0@<spark0-host> spark1@<spark1-host>
# optional: add --tcp 22 --tcp 29500 --tcp 9090
```

If you prefer an inventory-driven command (recommended for repeatable runs):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \
  --inventory-file deploy/config/inventory.ds4.spark01.example
```

Optional (recommended): capture a single “snapshot” (mesh + systemd status + optional journald tail) for run notes (safe):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp2 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark01.example
```

Note: snapshots may include hostnames/IPs/routes and journal excerpts; keep the output private and redact before sharing externally.

## 2) Install System Units + Config (Spark Side, Human Approval)

On each Spark, review the staged installer wrapper, then install (human-run):

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --start-preflight --preflight tp2
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark1 --start-preflight --preflight tp2
```

Then validate installed assets (safe; recommended before enabling DS4):

```bash
sudo /opt/ds4/scripts/ops_validate_installed_assets.sh --instance spark0 --strict
sudo /opt/ds4/scripts/ops_validate_installed_assets.sh --instance spark1 --strict
```

## 3) Run Strict Preflight (Safe Gate)

Run strict TP=2 preflight on each Spark (safe):

```bash
sudo systemctl start ds4-preflight-strict@spark0.service
sudo systemctl start ds4-preflight-strict@spark1.service
```

Tail the preflight logs (examples):

```bash
journalctl -u ds4-preflight-strict@spark0.service -n 200 --no-pager
journalctl -t ds4-preflight-strict-spark0 -n 200 --no-pager
```

## 4) Start DS4 (Optional; Human Approval)

If you want strict gating on start (recommended for early bring-up), enable the strict-start template:

```bash
sudo systemctl enable --now ds4-strict@spark0.service
sudo systemctl enable --now ds4-strict@spark1.service
```

See: `docs/deployment-systemd.md`.

## TP=2 → TP=3 Next Step (Add Spark2)

Once TP=2 readiness is consistently green on Spark0/Spark1, move to the 3-node ring docs:

- Quickstart: `docs/spark-ring-ops-quickstart-tp3.md`
- Readiness: `docs/spark-ring-ops-readiness-tp3.md`
- Checklist: `docs/spark-ring-ops-checklist-tp3.md`

