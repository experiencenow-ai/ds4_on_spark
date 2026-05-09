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

## What It Checks

- Required files exist under:
  - `deploy/systemd/`
  - `deploy/config/`
  - `deploy/sysusers.d/`, `deploy/tmpfiles.d/`
- All `scripts/ops*.sh` pass `sh -n` syntax checks
- Env examples include the keys required by `scripts/ops_ds4_env_check.sh`

## When To Use It

- Before staging templates to Spark0/Spark1 with `scripts/ops_stage_deploy_assets.sh`
- Before opening or merging ops-hardening PRs that change `deploy/` or `scripts/ops*.sh`
