# Spark Ring Ops Checklist (Spark0/Spark1 / TP=2 Baseline)

This is a **human-run** checklist for operating a 2-node baseline (Spark0 + Spark1) safely.

If you are setting up a fresh TP=2 baseline, start with:

- `docs/spark-ring-ops-quickstart-tp2.md`

For a one-page readiness rubric (what “ready” means, and what blocks a run), see:

- `docs/spark-ring-ops-readiness-tp2.md`

## Bring-up (Once)

- Initialize a private run directory for notes + snapshots (recommended): `RUN_DIR="$(./scripts/ops_run_dir_init.sh --tp tp2 --tag "<tag>")"`
- Pick stable hostnames for Spark0/Spark1 and decide whether you rely on mDNS (`*.local`) or pin `/etc/hosts` (see `deploy/config/hosts.ds4.spark01.example`).
- Recommended: keep the ordered inventory in a file so roles are explicit and repeatable (format example: `deploy/config/inventory.ds4.spark01.example`).
- Optional: take a read-only systemd status snapshot from the Mac (useful for run notes):
  - `./scripts/ops_spark_ring_status.sh --preflight tp2 --strict spark0@... spark1@...`
- Optional: capture a single combined snapshot (mesh + status; safe):
  - `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_tp2_$(date -u +%Y%m%d-%H%M%SZ).txt" --preflight tp2 --strict spark0@... spark1@...`
- Stage deploy assets + scripts from the Mac:
  - `./scripts/ops_stage_spark0_spark1.sh --mesh-check spark0@... spark1@...`
  - Optional (recommended): run staged TP readiness checks before any install/system changes (safe; uses staged `/tmp/ds4-*` assets):
    - `./scripts/ops_spark_ring_ops_check.sh --preflight tp2 --strict --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp2 spark0@... spark1@...`
- Install staged templates on each Spark:
  - `sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --start-preflight --preflight tp2`
  - `sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark1 --start-preflight --preflight tp2`
- Confirm systemd templates and scripts are present:
  - `/etc/systemd/system/ds4*.service`
  - `/opt/ds4/scripts/ops_tp2_readiness.sh`

## Developer Path (`systemd --user`) (Optional)

If you are doing a non-root bring-up (developer path), follow `docs/deployment-staged-systemd-user.md` and prefer strict gating:

- Preflight (safe gating): `systemctl --user start ds4-preflight-strict@spark0.service`
- Start DS4 (gated on strict preflight): `systemctl --user enable --now ds4-tp2-strict@spark0.service`
- Logs: `journalctl --user -u ds4-tp2-strict@spark0.service -n 200 --no-pager`

## Before A TP=2 Attempt (Repeatable)

- On both Sparks: confirm GPU visibility/health, kernel/driver versions, and time sanity (`timedatectl status`).
- Confirm your intended route interface (wired vs Wi‑Fi) and MTU; if you want to gate on interface, set `DS4_EXPECT_IFACE=<wired-ifname>` in `/etc/ds4/ds4-%i.env`.
- Ensure each instance has a correct rank and master settings:
  - `DS4_WORLD_SIZE=2`
  - `DS4_RANK=0/1`
  - `DS4_MASTER_ADDR=<spark0-host>` and `DS4_MASTER_PORT=<port>`
- On Spark0, ensure peer host is set for reachability checks:
  - `DS4_PEER_HOST=<spark1-host>`
- Run TP=2 strict preflight on both Sparks (safe):
  - `sudo systemctl start ds4-preflight-strict@spark0.service`
  - `sudo systemctl start ds4-preflight-strict@spark1.service`
- Confirm logs are flowing and easy to filter:
  - `journalctl -t ds4-spark1 -n 200 --no-pager`
- Confirm metrics reachability (best-effort):
  - `curl -fsS http://<spark1-host>:9090/metrics | head`

## During A TP=2 Attempt (Repeatable)

- On each Spark, tail instance logs (journald):
  - `journalctl -t ds4-spark0 -f`
  - `journalctl -t ds4-spark1 -f`
- Optional: capture a quick Mac-side systemd status snapshot (read-only):
  - `./scripts/ops_spark_ring_status.sh --preflight tp2 --strict spark0@... spark1@...`
- If you are scraping Prometheus, confirm target health and sample freshness (see `docs/ops-logging-metrics.md` and `deploy/config/prometheus-scrape.ds4.yml.example`).
- If an instance stops unexpectedly, capture a support bundle early (non-destructive; review before sharing):
  - `/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark1 --since "30 minutes ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark1.env`

## Planned Restart / Config Change (Repeatable)

Until DS4 documents a safe rolling restart for TP=2, treat restarts as a coordinated operation:

- Stop DS4 on both Sparks (pick an order and be consistent; example):
  - `sudo systemctl stop ds4@spark1.service ds4@spark0.service`
- Re-run strict TP=2 preflight (safe gating):
  - `sudo systemctl start ds4-preflight-strict@spark0.service`
  - `sudo systemctl start ds4-preflight-strict@spark1.service`
- Start DS4 again (example):
  - `sudo systemctl start ds4@spark0.service ds4@spark1.service`

## After A TP=2 Attempt (Repeatable)

- Snapshot the “what was running” facts (record in the run log):
  - `uname -a`
  - `nvidia-smi || true`
  - `systemctl status ds4@spark0.service --no-pager || true`
- If anything looked like a network or routing issue, follow the read-only inspection guidance:
  - `docs/ops-firewall-routing-inspection.md`

## If Something Fails

- Capture a support bundle on the failing instance (non-destructive; review before sharing):
  - `/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark0 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env`
- Use read-only routing/firewall inspection guidance:
  - `docs/ops-firewall-routing-inspection.md`
- Prefer documenting proposed network/systemd changes for human approval rather than applying them in automation loops.

## TP=2 → TP=3 Notes (Add Spark2)

- TP=2 readiness (Spark0/Spark1) is driven by `ds4-preflight@.service` / `ops_tp2_readiness.sh` and typically uses:
  - `DS4_MASTER_ADDR`/`DS4_MASTER_PORT`
  - `DS4_PEER_HOST` and optional `DS4_PEER_SSH`
- TP=3 readiness (Spark0/Spark1/Spark2) adds rank + ring host list:
  - `DS4_WORLD_SIZE=3`, `DS4_RANK=0/1/2`, `DS4_RING_HOSTS=...`
  - Run: `sudo systemctl start ds4-preflight-tp3-strict@spark0.service`
