# Spark Ring Ops Checklist (Spark0/Spark1/Spark2)

This is a **human-run** checklist for operating a 3-node ring layout safely.

## Bring-up (Once)

- Pick stable hostnames for Spark0/Spark1/Spark2 and decide whether you rely on mDNS (`*.local`) or pin `/etc/hosts` (see `deploy/config/hosts.ds4.spark012.example`).
- Stage deploy assets + scripts from the Mac:
  - `./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --topology ring ...` (stages TP=3 env variants via `DS4_ENV_VARIANT=tp3`)
- Install staged templates on each Spark:
  - `sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark2 --start-preflight`
- Confirm systemd templates and scripts are present:
  - `/etc/systemd/system/ds4*.service`
  - `/opt/ds4/scripts/ops_tp3_readiness.sh`

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

## If Something Fails

- Capture a support bundle on the failing instance (non-destructive; review before sharing):
  - `/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark2 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env`
- Use read-only routing/firewall inspection guidance:
  - `docs/ops-firewall-routing-inspection.md`
- Prefer documenting proposed network/systemd changes for human approval rather than applying them in automation loops.
