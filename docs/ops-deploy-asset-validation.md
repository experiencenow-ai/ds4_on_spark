# Ops: Deploy Asset Validation (Safe)

This repo includes a lightweight validator that checks the `deploy/` templates,
config examples, and `scripts/ops*.sh` helpers for internal consistency.

Nothing here changes Sparks automatically.

## Run (Mac Side)

From the repo root:

```bash
./scripts/ops_validate_deploy_assets.sh
```

## Run (Spark Side)

After staging deploy assets to a Spark (they land under `/tmp/ds4-*` by default):

```bash
/tmp/ds4-scripts/ops_validate_staged_assets.sh
```

Optional: install the staged assets (human-run; review first). This is a convenience wrapper around the manual `install` + `systemctl daemon-reload` steps documented in the deployment runbooks:

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --start-preflight
# optional: add --install-timers, --install-spark-units, and/or --strict
# dry-run preview:
# /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --dry-run
```

After installing systemd templates under `/etc/systemd/system/`, configs under `/etc/ds4/`, and scripts under `/opt/ds4/scripts/`:

```bash
/tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark0
```

Note: the periodic preflight timers (`ds4-preflight@.timer`, `ds4-preflight-strict@.timer`) are optional and are not required for `ops_validate_installed_assets.sh`.

## What It Checks

- Required files exist under:
  - `deploy/systemd/`
  - `deploy/config/`
  - `deploy/sysusers.d/`, `deploy/tmpfiles.d/`
- All `scripts/ops*.sh` pass `sh -n` syntax checks
- Env examples include the keys required by `scripts/ops_ds4_env_check.sh`
  - On-host, it also runs `ops_ds4_env_check.sh` (which validates `DS4_CONFIG_PATH` via `ops_ds4_config_check.sh` when present) + `ops_tp2_readiness.sh` against `/etc/ds4/`

## When To Use It

- Before staging templates to Spark0/Spark1 with `scripts/ops_stage_deploy_assets.sh`
- Before staging both Sparks in one flow with `scripts/ops_stage_spark0_spark1.sh`
- Before opening or merging ops-hardening PRs that change `deploy/` or `scripts/ops*.sh`
