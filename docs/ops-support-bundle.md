# Ops: DS4 Support Bundle (Safe)

When TP=2/TP=3/TP=4 preflight fails (or logs/metrics look suspicious), it helps to capture a small, repeatable “support bundle” from the Spark for debugging.

This bundle is **non-destructive**: it reads system state, systemd status, and journald logs. It does **not** change networking, system services, or GPU settings.

## Run (Spark Side)

If installed under `/opt/ds4/scripts/`:

```bash
/opt/ds4/scripts/ops_collect_support_bundle.sh --instance spark0 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env
```

You can also run it directly from a repo checkout:

```bash
./scripts/ops_collect_support_bundle.sh --instance spark0 --since "2 hours ago" --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env
```

The script prints an output `.tgz` path under `/tmp/` (and leaves the unpacked directory alongside it).

### Optional: Systemd Unit (Human Run)

If you install the systemd templates from `deploy/systemd/` to `/etc/systemd/system/`, you can also run the support bundle collector via:

```bash
sudo systemctl start ds4-support-bundle@spark0.service
```

`ds4-preflight@.service` and `ds4-preflight-strict@.service` are wired to trigger `ds4-support-bundle@%i.service` automatically on failure.

### Optional: Systemd --user Unit (Human Run)

If you install the user-service templates from `deploy/systemd-user/` (see `docs/deployment-systemd-user.md`), you can capture a support bundle without sudo:

```bash
systemctl --user start ds4-support-bundle@spark0.service
```

The user preflight templates in `deploy/systemd-user/` also trigger `ds4-support-bundle@%i.service` automatically on failure.

### Optional: Periodic Systemd Timer (Human Run)

If you want periodic bundles (for trend debugging), install + enable the timer template:

```bash
sudo install -m 0644 /tmp/ds4-systemd/ds4-support-bundle@.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ds4-support-bundle@spark0.timer
```

The default timer schedule is **weekly** with a randomized delay. Bundles land under `/tmp/` by default; review disk/retention expectations before enabling.

## What It Captures

Best-effort snapshots of:

- System info: date, kernel, distro info
- GPU info: `nvidia-smi` when present
- Network: `ip addr`, `ip route`, `ss -lntu`, best-effort `ip route get` for master/peer
- Systemd: `systemctl status/show` for `ds4@<instance>`, preflight, and strict-start units:
  - TP=2: `ds4-tp2-strict@<instance>` (legacy alias: `ds4-strict@<instance>`)
  - TP=3: `ds4-tp3-strict@<instance>`
  - TP=4: `ds4-tp4-strict@<instance>`
- Systemd (TP=3): `systemctl status` for `ds4-preflight-tp3@<instance>` and `ds4-preflight-tp3-strict@<instance>` when present
- Systemd (TP=4): `systemctl status` for `ds4-preflight-tp4@<instance>` and `ds4-preflight-tp4-strict@<instance>` when present
- Logs: `journalctl -u ... --since "<since>"`
- A small allowlist of DS4 env keys (not the full env files), including TP=4 context like `DS4_WORLD_SIZE`, `DS4_RANK`, and `DS4_RING_HOSTS` when provided
- DS4 config/env validation output when available:
  - `ops_ds4_config_check.sh --strict-unknown $DS4_CONFIG_PATH`
  - `ops_ds4_env_check.sh ...env...`
- A TP=2 readiness snapshot when env paths are provided (e.g. via the systemd unit):
  - `ops_tp2_readiness.sh --self <instance> --env ... [--peer <DS4_PEER_HOST>]`
- A TP=3 readiness snapshot when `ops_tp3_readiness.sh` is present and env paths are provided:
  - `ops_tp3_readiness.sh --self <instance> --topology ring --strict --env ...`
- A TP=4 readiness snapshot when `ops_tp4_readiness.sh` is present and env paths are provided:
  - `ops_tp4_readiness.sh --self <instance> --topology ring --strict --env ...`

## Redaction Guidance

The script avoids dumping whole env files, but you should still **review the bundle before sharing** and redact anything sensitive (hostnames, IPs, paths, etc.) as needed.
