# Ops: DS4 Support Bundle (Safe)

When TP=2 preflight fails (or logs/metrics look suspicious), it helps to capture a small, repeatable “support bundle” from the Spark for debugging.

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

## What It Captures

Best-effort snapshots of:

- System info: date, kernel, distro info
- GPU info: `nvidia-smi` when present
- Network: `ip addr`, `ip route`, `ss -lntu`, best-effort `ip route get` for master/peer
- Systemd: `systemctl status/show` for `ds4@<instance>`, preflight, strict variants
- Logs: `journalctl -u ... --since "<since>"`
- A small allowlist of DS4 env keys (not the full env files)

## Redaction Guidance

The script avoids dumping whole env files, but you should still **review the bundle before sharing** and redact anything sensitive (hostnames, IPs, paths, etc.) as needed.

