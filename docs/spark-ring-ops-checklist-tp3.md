# Spark Ring Ops Checklist (Spark0/Spark1/Spark2)

This is a **human-run** checklist for operating a 3-node ring layout safely.

## Bring-up (Once)

- Pick stable hostnames for Spark0/Spark1/Spark2 and decide whether you rely on mDNS (`*.local`) or pin `/etc/hosts` (see `deploy/config/hosts.ds4.spark012.example`).
- Recommended: keep the ordered inventory in a file so rank order is explicit and repeatable (format example: `deploy/config/inventory.ds4.spark012.example`).
- Optional: take a read-only systemd status snapshot from the Mac (useful for run notes):
  - `./scripts/ops_spark_ring_status.sh --preflight tp3 --strict spark0@... spark1@... spark2@...`
- Stage deploy assets + scripts from the Mac:
  - `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring spark0@... spark1@... spark2@...` (defaults to TP=3 env variants for a three-host inventory)
  - Confirm the staged env audit passes (safe; catches DS4 ring config mismatches before install): `scripts/ops_spark_ring_staged_env_audit.sh`
- Install staged templates on each Spark:
  - `sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark2 --start-preflight --preflight tp3`
- Confirm systemd templates and scripts are present:
  - `/etc/systemd/system/ds4*.service`
  - `/opt/ds4/scripts/ops_tp3_readiness.sh`

## Developer Path (`systemd --user`) (Optional)

If you are doing a non-root bring-up (developer path), follow `docs/deployment-staged-systemd-user.md` and prefer the TP=3 strict-start unit:

- Preflight (safe gating): `systemctl --user start ds4-preflight-tp3-strict@spark0.service`
- Start DS4 (gated on strict preflight): `systemctl --user enable --now ds4-tp3-strict@spark0.service`
- Logs: `journalctl --user -u ds4-tp3-strict@spark0.service -n 200 --no-pager`

## Before A TP=3 Attempt (Repeatable)

- On all 3 Sparks: confirm GPU visibility/health, kernel/driver versions, and time sanity (`timedatectl status`).
- Confirm your intended route interface (wired vs Wi‑Fi) and MTU; if you want to gate on interface, set `DS4_EXPECT_IFACE=<wired-ifname>` in `/etc/ds4/ds4-%i.env`.
- Ensure each instance has a correct rank + ring host list:
  - `DS4_WORLD_SIZE=3`
  - `DS4_RANK=0/1/2`
  - `DS4_RING_HOSTS=spark0.local,spark1.local,spark2.local` (or pinned hostnames)
- Run TP=3 strict preflight on each Spark (safe):
  - `sudo systemctl start ds4-preflight-tp3-strict@spark0.service`
- Confirm logs are flowing and easy to filter:
  - `journalctl -t ds4-spark2 -n 200 --no-pager`
- Confirm metrics reachability (best-effort):
  - `curl -fsS http://spark2.local:9090/metrics | head`

## During A TP=3 Attempt (Repeatable)

- On each Spark, tail instance logs (journald):
  - `journalctl -t ds4-spark0 -f`
  - `journalctl -t ds4-spark1 -f`
  - `journalctl -t ds4-spark2 -f`
- Optional: capture a quick Mac-side systemd status snapshot (read-only):
  - `./scripts/ops_spark_ring_status.sh --preflight tp3 --strict spark0@... spark1@... spark2@...`
- If you are scraping Prometheus, confirm target health and sample freshness (see `docs/ops-logging-metrics.md` and `deploy/config/prometheus-scrape.ds4.yml.example`).
- If an instance stops unexpectedly, capture a support bundle early (non-destructive; review before sharing):
  - `/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark1 --since "30 minutes ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark1.env`

## Planned Restart / Config Change (Repeatable)

Until DS4 documents a safe rolling restart for TP=3, treat restarts as a coordinated operation:

- Stop DS4 on all 3 Sparks (pick an order and be consistent; example):
  - `sudo systemctl stop ds4@spark2.service ds4@spark1.service ds4@spark0.service`
- Re-run strict TP=3 preflight (safe gating):
  - `sudo systemctl start ds4-preflight-tp3-strict@spark0.service`
  - `sudo systemctl start ds4-preflight-tp3-strict@spark1.service`
  - `sudo systemctl start ds4-preflight-tp3-strict@spark2.service`
- Start DS4 again (example):
  - `sudo systemctl start ds4@spark0.service ds4@spark1.service ds4@spark2.service`
- If you use the strict-start template, prefer `ds4-tp3-strict@%i.service` (TP=3-gated) rather than `ds4-strict@%i.service` (TP=2-gated):
  - `sudo systemctl start ds4-tp3-strict@spark0.service`

## After A TP=3 Attempt (Repeatable)

- Snapshot the “what was running” facts (record in the run log):
  - `uname -a`
  - `nvidia-smi || true`
  - `systemctl status ds4@spark0.service --no-pager || true`
- If anything looked like a network or routing issue, follow the read-only inspection guidance:
  - `docs/ops-firewall-routing-inspection.md`

## If Something Fails

- Capture a support bundle on the failing instance (non-destructive; review before sharing):
  - `/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark2 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env`
- Use read-only routing/firewall inspection guidance:
  - `docs/ops-firewall-routing-inspection.md`
- Prefer documenting proposed network/systemd changes for human approval rather than applying them in automation loops.

## TP=2 → TP=3 Readiness Delta (Notes)

- TP=2 readiness (Spark0/Spark1) is driven by `ds4-preflight@.service` / `ops_tp2_readiness.sh` and typically uses:
  - `DS4_PEER_HOST` and optional `DS4_PEER_SSH`
- TP=3 readiness (Spark0/Spark1/Spark2) adds rank + ring host list:
  - `DS4_WORLD_SIZE=3`, `DS4_RANK=0/1/2`, `DS4_RING_HOSTS=...`
  - Run: `sudo systemctl start ds4-preflight-tp3-strict@spark0.service`
