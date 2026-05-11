# Ops: TP=4 Readiness Checks (Safe)

TP=4 here means 4-node distributed execution (Spark0 + Spark1 + Spark2 + Spark3).

These checks are designed to be **non-destructive** and safe to run repeatedly.
They do not change networking, system services, or GPU settings.

## Ring Host List

For TP=4, prefer setting a rank-ordered host list in `/etc/ds4/ds4-%i.env`:

```bash
DS4_RING_HOSTS=spark0.local,spark1.local,spark2.local,spark3.local
```

The readiness script uses this list to derive ring neighbors (prev/next) based on `DS4_RANK`.

## Commands (Spark Side)

Ad-hoc run (no systemd required):

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp4_readiness.sh --self spark2 --topology ring --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env
```

Strict gating (fails non-zero if required TP=4 inputs are missing/invalid):

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp4_readiness.sh --strict --self spark2 --topology ring --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env
```

What the script checks (best-effort, safe):

- `DS4_WORLD_SIZE==4` and `DS4_RANK in 0..3` (strict mode)
- host resolution + `ip route get` hints for master + selected peers
- optional expected route interface checks via `DS4_EXPECT_IFACE`
- best-effort peer ping checks (ring neighbors by default)
- best-effort peer metrics probes (`http://<peer>:${DS4_METRICS_PORT}/metrics`) when `curl` is available

## Systemd Hook (Optional)

If you install templates under `/etc/systemd/system/`, you can run TP=4 preflight as a oneshot:

```bash
sudo systemctl start ds4-preflight-tp4@spark0.service
```

Strict variant:

```bash
sudo systemctl start ds4-preflight-tp4-strict@spark0.service
```

Logs:

```bash
journalctl -u ds4-preflight-tp4@spark0.service -n 200 --no-pager
journalctl -t ds4-preflight-tp4-spark0 -n 200 --no-pager
```

If strict preflight fails and you have `ds4-support-bundle@.service` installed, systemd triggers a non-destructive support bundle. See `docs/ops-support-bundle.md`.

## Optional: Periodic TP=4 Preflight (Systemd Timer)

If you want readiness checks to run automatically on boot and periodically after,
install and enable the timer template (human-run):

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-tp4@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight-tp4@spark0.timer
```

Strict variant (fails non-zero on missing/invalid TP=4 inputs; human-run):

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4-preflight-tp4-strict@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-preflight-tp4-strict@spark0.timer
```
