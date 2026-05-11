# Deployment: Staged `systemd --user` Install (Spark Side, No Sudo)

This runbook covers a **non-root** bring-up path using `deploy/systemd-user/` templates.

It assumes you staged deploy assets to the Spark via `scripts/ops_stage_deploy_assets.sh` (Mac-side), so the Spark has:

- `/tmp/ds4-systemd-user/` (unit templates)
- `/tmp/ds4-config/` (env/config examples)
- `/tmp/ds4-scripts/` (ops scripts + installers)

## Preconditions (Human Check)

On the Spark, these templates expect a DS4 checkout at:

```bash
ls -la "$HOME/ds4"
```

and a built server binary at:

```bash
ls -la "$HOME/ds4/bin/ds4_server"
```

## Install (Human Run)

Pick the instance name for the host (typically `spark0`, `spark1`, or `spark2`) and run:

```bash
/tmp/ds4-scripts/ops_install_staged_assets_user.sh --instance spark0 --start-preflight
```

This installs:

- user-unit templates under `~/.config/systemd/user/`
- env/config files under `~/.config/ds4/`
- required readiness scripts under `$HOME/ds4/scripts/`

## Validate (Optional, Human Run)

```bash
/tmp/ds4-scripts/ops_validate_user_installed_assets.sh --instance spark0 --strict
```

## Enable + Start (Human Run)

```bash
systemctl --user enable --now ds4@spark0.service
```

## Logs (Human Run)

```bash
journalctl --user -u ds4@spark0.service -n 200 --no-pager
journalctl --user -u ds4-preflight@spark0.service -n 200 --no-pager
```

## Run Without Login Sessions (Optional, Human Approval)

If you want user services to keep running after logout, host policy may require lingering:

```bash
sudo loginctl enable-linger <your-username>
```

Do not enable lingering without explicit approval and a retention plan for user logs/state.

