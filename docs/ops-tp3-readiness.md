# Ops: TP=3 Readiness Checks (Safe)

TP=3 here means 3-node distributed execution (Spark0 + Spark1 + Spark2).

These checks are designed to be **non-destructive** and safe to run repeatedly.
They do not change networking, system services, or GPU settings.

## Ring Host List

For TP=3, prefer setting a rank-ordered host list in `/etc/ds4/ds4-%i.env`:

```bash
DS4_RING_HOSTS=spark0.local,spark1.local,spark2.local
```

The readiness script uses this list to derive ring neighbors (prev/next) based on `DS4_RANK`.

Notes:

- `DS4_RING_HOSTS` must have exactly 3 comma-separated entries (no trailing commas). In strict mode, invalid or duplicate entries fail non-zero.
- When using `--topology full`, the script uses `DS4_RANK` + `DS4_RING_HOSTS` to skip self and probe only peers.

## Commands (Mac Side, Staged Assets)

If you staged deploy assets first (so each Spark has `/tmp/ds4-scripts/` and `/tmp/ds4-config/`), you can run TP readiness checks **before installing** anything under `/etc` or systemd (safe; no sudo):

```bash
./scripts/ops_stage_spark_ring.sh --mesh-check --staged-readiness --staged-readiness-strict --topology ring \
  spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

Or run staged readiness directly after staging:

```bash
./scripts/ops_spark_ring_staged_readiness.sh --preflight tp3 --strict --topology ring \
  spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

Optional (recommended during TP=2 → TP=3 transition): run TP=2 readiness checks *and* TP=3 readiness checks (safe):

```bash
./scripts/ops_spark_ring_staged_readiness.sh --preflight tp23 --strict --topology ring \
  spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

The staged helper runs `/tmp/ds4-scripts/ops_tp3_readiness.sh` on each Spark with:

- `--env -/tmp/ds4-config/ds4.env.example`
- `--env /tmp/ds4-config/ds4-<instance>.env.example`

## Commands (Spark Side)

Ad-hoc run (no systemd required):

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp3_readiness.sh --self spark2 --topology ring --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env
```

Strict gating (fails non-zero if required TP=3 inputs are missing/invalid):

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp3_readiness.sh --strict --self spark2 --topology ring --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env
```

Deeper debug (checks all peers, not just ring neighbors; still non-destructive):

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp3_readiness.sh --strict --self spark2 --topology full --tcp 29500 --tcp 9090 --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env
```

What the script checks (best-effort, safe):

- `DS4_WORLD_SIZE==3` and `DS4_RANK in 0..2` (strict mode)
- `DS4_MASTER_ADDR` consistency with the ring rank0 host (strict mode; best-effort via IPv4 resolution)
- host resolution + `ip route get` hints for master + selected peers
- optional expected route interface checks via `DS4_EXPECT_IFACE`
- best-effort peer ping checks (ring neighbors by default)
- best-effort peer metrics probes (`http://<peer>:${DS4_METRICS_PORT}/metrics`) when `curl` is available

## Systemd Hook (Optional)

If you install templates under `/etc/systemd/system/`, you can run TP=3 preflight as a oneshot:

```bash
sudo systemctl start ds4-preflight-tp3@spark0.service
```

Strict variant:

```bash
sudo systemctl start ds4-preflight-tp3-strict@spark0.service
```

Logs:

```bash
journalctl -u ds4-preflight-tp3@spark0.service -n 200 --no-pager
journalctl -t ds4-preflight-tp3-spark0 -n 200 --no-pager
```

If strict preflight fails and you have `ds4-support-bundle@.service` installed, systemd triggers a non-destructive support bundle. See `docs/ops-support-bundle.md`.

## Optional: Periodic TP=3 Preflight (Systemd Timer)

If you want readiness checks to run automatically on boot and periodically after,
install and enable the timer template (human-run):

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-tp3@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight-tp3@spark0.timer
```

Strict variant (fails non-zero on missing/invalid TP=3 inputs; human-run):

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-tp3-strict@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight-tp3-strict@spark0.timer
```
