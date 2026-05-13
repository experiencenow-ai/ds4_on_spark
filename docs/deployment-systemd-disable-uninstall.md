# Systemd Disable / Uninstall (Human Runbook)

This repo does not apply changes to Sparks automatically. Everything below is **human-run**.

Goal: safely stop/disable DS4 systemd units (and optional timers), and optionally remove installed unit files + configs if you need to roll back a deployment layout.

Nothing here changes Spark networking, firewall rules, or GPU settings.

## Before You Change Anything (Recommended)

- Write down which topology you are in (TP=2 vs TP=3) and which instances exist (`spark0`, `spark1`, `spark2`).
- Capture a read-only snapshot for run notes (recommended):
  - `RUN_DIR="$(./scripts/ops_run_dir_init.sh --tp tp3 --tag "<tag>")"`
  - `./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_pre_disable_$(date -u +%Y%m%d-%H%M%SZ).txt" --preflight tp3 --strict --inventory-file deploy/config/inventory.ds4.spark012.example`
- On each Spark: `sudo systemctl status ds4@spark0.service --no-pager || true` (replace instance as needed).

## System Units (Root / `/etc/systemd/system`)

### 1) Stop DS4 (Coordinated)

For a 3-node ring, treat stops as coordinated unless DS4 explicitly documents a safe rolling restart.

Example (stop in reverse rank order):

```bash
sudo systemctl stop ds4@spark2.service ds4@spark1.service ds4@spark0.service
```

If you run strict-start units, stop those instead (only one of these should be enabled per instance):

```bash
sudo systemctl stop ds4-tp3-strict@spark0.service || true
sudo systemctl stop ds4-tp2-strict@spark0.service || true
sudo systemctl stop ds4-strict@spark0.service || true  # legacy alias name
```

### 2) Disable Units (Prevent Auto-Start)

Disable the long-running unit(s) you enabled:

```bash
sudo systemctl disable ds4@spark0.service || true
sudo systemctl disable ds4-tp3-strict@spark0.service || true
sudo systemctl disable ds4-tp2-strict@spark0.service || true
sudo systemctl disable ds4-strict@spark0.service || true
```

Optional: disable any timers you enabled (repeat for each instance you used):

```bash
sudo systemctl disable ds4-preflight@spark0.timer || true
sudo systemctl disable ds4-preflight-strict@spark0.timer || true
sudo systemctl disable ds4-preflight-tp3@spark0.timer || true
sudo systemctl disable ds4-preflight-tp3-strict@spark0.timer || true
sudo systemctl disable ds4-preflight-tp4@spark0.timer || true
sudo systemctl disable ds4-preflight-tp4-strict@spark0.timer || true
sudo systemctl disable ds4-support-bundle@spark0.timer || true
```

Note: preflight services are oneshot and do not stay “enabled” unless you created custom wiring; disabling is mainly for timers and long-running instances.

### 3) Remove Installed Unit Files (Optional; Destructive)

Only do this if you intend to remove DS4’s systemd integration from the host.

If you installed via `/tmp/ds4-scripts/ops_install_staged_assets.sh`, DS4 templates live under:

- `/etc/systemd/system/` (`ds4*.service`, optional `ds4*.timer`, optional `spark-*.service`)

Remove the unit files, then reload systemd:

```bash
sudo rm -f /etc/systemd/system/ds4*.service /etc/systemd/system/ds4*.timer
sudo rm -f /etc/systemd/system/spark-master@.service /etc/systemd/system/spark-worker@.service
sudo systemctl daemon-reload
sudo systemctl reset-failed || true
```

### 4) Remove Config Files (Optional; Destructive)

DS4 config/env files are typically under `/etc/ds4/`:

```bash
sudo ls -la /etc/ds4 || true
```

If you want to remove DS4’s host config completely:

```bash
sudo rm -f /etc/ds4/ds4.env /etc/ds4/ds4-spark*.env /etc/ds4/ds4-spark*.conf
```

If you have local secrets or host-specific values, archive first.

### 5) Remove Installed Ops Scripts (Optional; Destructive)

Installed scripts are typically under `/opt/ds4/scripts/`.

Remove only if you are sure nothing else on the host expects them:

```bash
sudo rm -f /opt/ds4/scripts/ops_*.sh
```

### 6) Remove State/Logs (Optional; Destructive)

The system units create state/log directories via `StateDirectory=` and `LogsDirectory=`.
Typical locations:

- `/var/lib/ds4/`
- `/var/log/ds4/`

These directories may contain model/cache data and operational artifacts; treat removal as destructive:

```bash
sudo du -sh /var/lib/ds4 /var/log/ds4 2>/dev/null || true
# optionally archive first, then:
# sudo rm -rf /var/lib/ds4 /var/log/ds4
```

## User Units (`systemd --user`) (Optional Path)

If you installed user units under `~/.config/systemd/user/` and configs under `~/.config/ds4/`:

```bash
systemctl --user stop ds4@spark0.service || true
systemctl --user disable ds4@spark0.service || true
systemctl --user disable ds4-tp3-strict@spark0.service || true
systemctl --user disable ds4-tp2-strict@spark0.service || true
systemctl --user disable ds4-strict@spark0.service || true
systemctl --user disable ds4-preflight@spark0.timer || true
systemctl --user disable ds4-support-bundle@spark0.timer || true
systemctl --user daemon-reload
systemctl --user reset-failed || true
```

Then remove user unit/config files (optional; destructive):

```bash
rm -f ~/.config/systemd/user/ds4*.service ~/.config/systemd/user/ds4*.timer
rm -rf ~/.config/ds4
systemctl --user daemon-reload
```

If you enabled lingering to run user services without a login session, decide whether it should remain enabled (host policy dependent):

```bash
sudo loginctl disable-linger <your-username>
```

Do not disable lingering unless you understand the host’s policy and have explicit approval.

## Post-Checks (Recommended)

On each Spark:

```bash
sudo systemctl list-units --all 'ds4*' --no-pager || true
sudo systemctl list-unit-files 'ds4*' --no-pager || true
```

If you removed unit files, confirm there are no remaining drop-ins under:

- `/etc/systemd/system/ds4@.service.d/`
- `/etc/systemd/system/ds4@spark0.service.d/` (instance-specific)

If you use a Mac-side run directory, capture a post-change snapshot for run notes:

```bash
./scripts/ops_spark_ring_ops_check.sh --out "${RUN_DIR:-/private/tmp}/ds4_ops_check_post_disable_$(date -u +%Y%m%d-%H%M%SZ).txt" --preflight tp3 --strict --inventory-file deploy/config/inventory.ds4.spark012.example
```

