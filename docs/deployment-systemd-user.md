# Systemd User-Service Templates (Optional)

This repo primarily targets **system** systemd units under `/etc/systemd/system/` (see `docs/deployment-systemd.md`).

For developer bring-up or non-root runs, `deploy/systemd-user/` includes **optional** templates intended for `systemd --user`.

These templates are not staged by `scripts/ops_stage_deploy_assets.sh`; treat them as manual-copy references.

## Install (Human Runbook)

Copy templates to your user-unit directory:

```bash
install -d -m 0755 ~/.config/systemd/user
cp deploy/systemd-user/ds4*.service ~/.config/systemd/user/
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
systemctl --user enable --now ds4@spark0.service
```

Logs:

```bash
journalctl --user -u ds4@spark0.service -n 200 --no-pager
journalctl --user -t ds4-user-spark0 -n 200 --no-pager
```

## Run Without Login Sessions (Optional)

To keep user services running when you log out, you may need lingering (host policy-dependent; human-run):

```bash
sudo loginctl enable-linger <your-username>
```

Do not enable lingering unless you understand the host’s policy and have explicit approval.

