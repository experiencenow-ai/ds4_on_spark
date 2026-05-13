# Systemd User-Service Templates (Optional)

This repo primarily targets **system** systemd units under `/etc/systemd/system/` (see `docs/deployment-systemd.md`).

For developer bring-up or non-root runs, `deploy/systemd-user/` includes **optional** templates intended for `systemd --user`.

These templates are staged by `scripts/ops_stage_deploy_assets.sh` under `/tmp/ds4-systemd-user/` on the Spark (reference only; user units are installed manually).
Optional user drop-in examples are staged under `/tmp/ds4-systemd-user-dropins/` and tracked in-repo under `deploy/systemd-user-dropins/`.

Spark standalone user-service templates are also available (optional): see `docs/deployment-spark-standalone-systemd-user.md`.

## Install (Human Runbook)

Copy templates to your user-unit directory:

```bash
install -d -m 0755 ~/.config/systemd/user
cp deploy/systemd-user/ds4*.service ~/.config/systemd/user/
cp deploy/systemd-user/ds4*.timer ~/.config/systemd/user/ 2>/dev/null || true  # optional (timers)
systemctl --user daemon-reload
```

Create per-instance env + config files (example):

```bash
install -d -m 0755 ~/.config/ds4
cp deploy/config/ds4.env.example ~/.config/ds4/ds4.env
cp deploy/config/ds4-spark0.env.example ~/.config/ds4/ds4-spark0.env
cp deploy/config/ds4-spark0.conf.example ~/.config/ds4/ds4-spark0.conf
```

Then adjust paths in `~/.config/ds4/ds4-*.env` to match your user-space DS4 checkout:

- `DS4_HOME=$HOME/ds4`
- `DS4_CONFIG_PATH=$HOME/.config/ds4/ds4-<instance>.conf`

Enable/start:

```bash
systemctl --user start ds4-preflight@spark0.service
# strict gating (fails non-zero on missing/invalid TP=2 inputs):
# systemctl --user start ds4-preflight-strict@spark0.service
# optional TP=3/TP=4 preflight templates:
# systemctl --user start ds4-preflight-tp3@spark0.service
# systemctl --user start ds4-preflight-tp3-strict@spark0.service
# systemctl --user start ds4-preflight-tp4@spark0.service
# systemctl --user start ds4-preflight-tp4-strict@spark0.service
systemctl --user enable --now ds4@spark0.service

# strict DS4 start (requires ds4-preflight-strict@%i):
# systemctl --user enable --now ds4-strict@spark0.service

# strict DS4 start (TP=3 / TP=4; requires the matching strict topology preflight):
# systemctl --user enable --now ds4-tp3-strict@spark0.service
# systemctl --user enable --now ds4-tp4-strict@spark0.service

# optional (collect a support bundle on preflight failure or by hand):
systemctl --user start ds4-support-bundle@spark0.service

# optional (periodic support bundle timer; defaults to weekly):
# systemctl --user enable --now ds4-support-bundle@spark0.timer
```

Optional: periodic preflight timers (safe, non-destructive):

```bash
systemctl --user enable --now ds4-preflight@spark0.timer
# TP=3 / TP=4 variants:
# systemctl --user enable --now ds4-preflight-tp3@spark0.timer
# systemctl --user enable --now ds4-preflight-tp4@spark0.timer
```

Logs:

```bash
journalctl --user -u ds4@spark0.service -n 200 --no-pager
journalctl --user -t ds4-user-spark0 -n 200 --no-pager
```

## Unit Overrides (Drop-Ins) (Optional)

Prefer `systemctl --user edit` for overrides instead of editing the base unit files in `deploy/systemd-user/`:

```bash
# Instance-specific:
systemctl --user edit ds4@spark0.service

# Template-wide:
systemctl --user edit ds4@.service
```

Example snippets (copy/paste starting points):

- `deploy/systemd-user-dropins/README.md`
- `deploy/systemd-user-dropins/ds4@.service.d/20-timeouts.conf.example`
- `deploy/systemd-user-dropins/ds4@.service.d/40-execstart-override.conf.example`

## Run Without Login Sessions (Optional)

To keep user services running when you log out, you may need lingering (host policy-dependent; human-run):

```bash
sudo loginctl enable-linger <your-username>
```

Do not enable lingering unless you understand the host’s policy and have explicit approval.
