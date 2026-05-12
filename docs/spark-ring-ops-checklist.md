# Example Spark Ring Ops Checklist (Spark0..Spark3)

Prefer inventory-driven helpers for new work:

- `scripts/ops_spark_ring_mesh_check.sh <spark0> <spark1> [spark2 ...]`
- `scripts/ops_stage_spark_ring.sh <spark0> <spark1> [spark2 ...]`

The current 3-node checklist remains:

- `docs/spark-ring-ops-checklist-tp3.md`

This file is retained as a 4-node example, not as a source of truth for the active inventory.

This is a **human-run** checklist for operating a 4-node ring layout safely.

## Bring-up (Once)

- Pick stable hostnames for the example four-node ring and decide whether you rely on mDNS (`*.local`) or pin `/etc/hosts` (see `deploy/config/hosts.ds4.spark_ring.example`).
- Recommended: keep the ordered inventory in a file so rank order is explicit and repeatable (format example: `deploy/config/inventory.ds4.spark_ring.example`).
- Stage deploy assets + scripts from the Mac:
  - `./scripts/ops_stage_spark_ring.sh --mesh-check --topology ring ...` (stages TP=4 env variants via `DS4_ENV_VARIANT=tp4`)
  - Confirm the staged env audit passes (safe; catches DS4 ring config mismatches before install): `scripts/ops_spark_ring_staged_env_audit.sh`
- Install staged templates on each Spark:
  - `sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark2 --start-preflight --preflight tp4`
- Confirm systemd templates and scripts are present:
  - `/etc/systemd/system/ds4*.service`
  - `/opt/ds4/scripts/ops_tp4_readiness.sh`

## Before A TP=4 Attempt (Repeatable)

- On all 4 Sparks: confirm GPU visibility/health, kernel/driver versions, and time sanity (`timedatectl status`).
- Confirm your intended route interface (wired vs Wi‑Fi) and MTU; if you want to gate on interface, set `DS4_EXPECT_IFACE=<wired-ifname>` in `/etc/ds4/ds4-%i.env`.
- Run TP=4 strict preflight on each Spark (safe):
  - `sudo systemctl start ds4-preflight-tp4-strict@spark0.service`
- Confirm logs are flowing and easy to filter:
  - `journalctl -t ds4-spark2 -n 200 --no-pager`
- Confirm metrics reachability (best-effort):
  - `curl -fsS http://spark2.local:9090/metrics | head`

## If Something Fails

- Capture a support bundle on the failing instance (non-destructive; review before sharing):
  - `/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark2 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env`
- Use read-only routing/firewall inspection guidance:
  - `docs/ops-firewall-routing-inspection.md`
- Prefer documenting proposed network/systemd changes for human approval rather than applying them in automation loops.
