# Ops: TP=2 + TP=3 Readiness Checks (Safe, Transition Helper)

TP=2 here means dual-Spark distributed execution (Spark0 + Spark1).

TP=3 here means 3-node distributed execution (Spark0 + Spark1 + Spark2).

This doc covers a **non-destructive** “run both” readiness path intended for TP=2 -> TP=3 transition periods.

## One Command Snapshot (Mac Side, Safe)

To capture a single snapshot (mesh + systemd status + optional journald tail) across an ordered Spark0/Spark1/Spark2 inventory:

```bash
./scripts/ops_spark_ring_ops_check.sh --out "/private/tmp/ds4_ops_check_tp23_$(date -u +%Y%m%d-%H%M%SZ).txt" \
  --preflight tp23 --strict --journal --lines 120 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

If you already staged deploy assets to `/tmp/ds4-*` on all Sparks, you can also include staged readiness checks (safe; no sudo):

```bash
./scripts/ops_spark_ring_ops_check.sh --preflight tp23 --strict --journal --lines 120 \
  --staged-readiness --staged-readiness-strict --staged-readiness-preflight tp23 \
  --inventory-file deploy/config/inventory.ds4.spark012.example
```

## Commands (Spark Side, Safe)

Ad-hoc run (no systemd required):

```bash
sudo -u ds4 /opt/ds4/scripts/ops_tp23_readiness.sh --strict --self spark2 \
  --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark2.env
```

This runs `ops_tp2_readiness.sh` then `ops_tp3_readiness.sh` using the same env inputs.

## Systemd Hook (Optional)

If you install templates under `/etc/systemd/system/`, you can run the combined preflight oneshot:

```bash
sudo systemctl start ds4-preflight-tp23@spark0.service
sudo systemctl start ds4-preflight-tp23-strict@spark0.service
```

### Periodic Systemd Timer (Optional)

If you installed timer templates (for example by adding `--install-timers` when running `/tmp/ds4-scripts/ops_install_staged_assets.sh`), you can enable periodic `tp23` preflight checks:

```bash
sudo systemctl enable --now ds4-preflight-tp23-strict@spark0.timer
```

Logs:

```bash
journalctl -u ds4-preflight-tp23@spark0.service -n 200 --no-pager
journalctl -t ds4-preflight-tp23-spark0 -n 200 --no-pager
```

`systemd --user` is also supported (developer bring-up):

```bash
systemctl --user start ds4-preflight-tp23-strict@spark0.service
```

### Periodic `systemd --user` Timer (Optional)

If you installed the user timer templates under `~/.config/systemd/user/`, you can enable periodic checks without sudo:

```bash
systemctl --user enable --now ds4-preflight-tp23-strict@spark0.timer
```

If strict preflight fails and `ds4-support-bundle@.service` is installed, systemd triggers a non-destructive support bundle. See `docs/ops-support-bundle.md`.
