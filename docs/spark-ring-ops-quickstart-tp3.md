# Spark Ring Ops Quickstart (Spark0/Spark1/Spark2 / TP=3)

This is a **human-run** quickstart for a 3-node ring layout (Spark0/Spark1/Spark2).

Nothing here should be applied automatically. Review any `sudo`/systemd changes on the Sparks before running them.

Use this alongside:

- Deployment layout: `docs/deployment-spark0-spark1-spark2.md`
- Staged layout: `docs/deployment-spark012-staged-layout.md`
- SSH + network runbook: `docs/ops-ssh-network-runbook.md`
- Logging + metrics conventions: `docs/ops-logging-metrics.md`
- Operating checklist: `docs/spark-ring-ops-checklist-tp3.md`
- Readiness rubric: `docs/spark-ring-ops-readiness-tp3.md`

## 0) Choose Names + Inventory (Mac Side)

- Decide whether you rely on mDNS (`spark0.local`) or pin `/etc/hosts` (examples: `deploy/config/hosts.ds4.spark012.example`).
- Prefer an ordered inventory file so rank order is explicit and repeatable:
  - `deploy/config/inventory.ds4.spark012.example`

Recommended Mac-side SSH defaults (dedicated known-hosts file):

```bash
export SSH_OPTS='-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts'
```

## 1) Stage Deploy Assets + Scripts (Mac Side, Safe)

Validate the repo’s deploy assets and ops scripts (safe):

```bash
./scripts/ops_validate_deploy_assets.sh
```

Stage templates/config examples/scripts to all 3 hosts (safe; non-destructive):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

Optional (recommended): run staged TP readiness checks immediately after staging (safe; no sudo; uses staged `/tmp/ds4-*` assets):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp3 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

Optional: capture a single “snapshot” (mesh + systemd status + optional journald tail) for run notes (safe):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp3_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp3 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

Note: snapshots may include hostnames/IPs/routes and journal excerpts; keep the output private and redact before sharing externally.

Optional: if you already staged assets, include staged readiness in the same snapshot (safe; uses `/tmp/ds4-*`):

```bash
./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp3_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp3 --strict --journal --lines 120 \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp3 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

## 2) Install System Units + Config (Spark Side, Human Approval)

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

## 3) Run Strict Readiness Gates (Spark Side, Safe)

TP=3 strict preflight (safe oneshot; fails non-zero on missing/invalid TP=3 inputs):

```bash
sudo systemctl start ds4-preflight-tp3-strict@spark0.service
sudo systemctl start ds4-preflight-tp3-strict@spark1.service
sudo systemctl start ds4-preflight-tp3-strict@spark2.service
```

If you want a baseline TP=2 sanity pass (Spark0/Spark1 only), you can also run:

```bash
sudo systemctl start ds4-preflight-strict@spark0.service
sudo systemctl start ds4-preflight-strict@spark1.service
```

## 4) Start DS4 (Spark Side, Human Approval)

For early bring-up, prefer strict TP=3 gating on start:

```bash
sudo systemctl enable --now ds4-tp3-strict@spark0.service
sudo systemctl enable --now ds4-tp3-strict@spark1.service
sudo systemctl enable --now ds4-tp3-strict@spark2.service
```

## 5) Logs + Metrics (Spark Side, Safe)

Logs (journald):

```bash
journalctl -t ds4-spark0 -n 200 --no-pager
journalctl -t ds4-spark1 -n 200 --no-pager
journalctl -t ds4-spark2 -n 200 --no-pager
```

Metrics (best-effort, if enabled):

```bash
curl -fsS http://spark0.local:9090/metrics | head
```

Conventions + examples:

- `docs/ops-logging-metrics.md`
- `deploy/config/prometheus-scrape.ds4.yml.example`
- `deploy/config/prometheus-alerts.ds4.yml.example`

## 6) If Something Looks Wrong (Spark Side, Safe)

Capture a non-destructive support bundle early (review before sharing; redaction may be required):

```bash
/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark2 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env
```

Runbook: `docs/ops-support-bundle.md`.

If it smells like routing/firewall/name resolution, use the read-only inspection guidance:

- `docs/ops-firewall-routing-inspection.md`

Do not change Spark networking or system services as part of automation loops; record proposed changes for human approval.

## Note: Centaur Ops Hooks (Do Not Run Smoke Here)

Centaur-on-Spark has its own runbooks and smoke workflows. Keep Centaur feature smoke tests in the Centaur Spark loop; do not bundle them into DS4 ring ops bring-up.
