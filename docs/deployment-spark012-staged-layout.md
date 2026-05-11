# Deployment: Spark0/Spark1/Spark2 Staged Layout (TP=3 Prep)

This document summarizes a safe, repeatable **three-node** deployment layout for Spark0/Spark1/Spark2.

It is intended for **human-run** ops. Nothing here should be applied automatically.

## Goals

- Keep host identity explicit (`spark0`, `spark1`, `spark2`) and avoid username inference.
- Use staged deploy assets under `/tmp/ds4-*` for review before installation.
- Prefer preflight checks (`ops_tp2_readiness.sh` / `ops_tp3_readiness.sh`) before enabling DS4.

## Mac Side: Stage Assets To All 3 Nodes

Use the wrapper that validates once, then stages to Spark0/Spark1/Spark2:

```bash
./scripts/ops_stage_spark0_spark1_spark2.sh --mesh-check --topology ring \
  spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

On each Spark, you should now have:

- `/tmp/ds4-systemd/` and `/tmp/ds4-systemd-user/`
- `/tmp/ds4-config/`
- `/tmp/ds4-sysusers/` and `/tmp/ds4-tmpfiles/`
- `/tmp/ds4-scripts/`

## Spark Side (System Units): Install + Preflight (Human Approval)

If you are using system units under `/etc/systemd/system/` and `/etc/ds4/`:

```bash
sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance spark0 --start-preflight
sudo /tmp/ds4-scripts/ops_validate_installed_assets.sh --instance spark0 --strict
```

Repeat for `spark1` and `spark2`.

## Spark Side (`systemd --user`): Install + Preflight (No Sudo)

If you are doing a non-root bring-up (developer path), use the staged installer:

```bash
/tmp/ds4-scripts/ops_install_staged_assets_user.sh --instance spark0 --start-preflight
/tmp/ds4-scripts/ops_validate_user_installed_assets.sh --instance spark0 --strict
systemctl --user enable --now ds4@spark0.service
```

Repeat for `spark1` and `spark2`.

## Three-Node Ring Ops Checklist

Use the canonical operating checklist:

- `docs/spark-ring-ops-checklist.md`

For the TP=3-specific checklist variant (when relevant):

- `docs/spark-ring-ops-checklist-tp3.md`

## Readiness Checks (Safe)

Run these from a system context:

```bash
/opt/ds4/scripts/ops_tp2_readiness.sh --self spark0 --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env --strict
/opt/ds4/scripts/ops_tp3_readiness.sh --self spark0 --env -/etc/ds4/ds4.env --env /etc/ds4/ds4-spark0.env --strict
```

Or from the user-service context:

```bash
$HOME/ds4/scripts/ops_tp2_readiness.sh --self spark0 --env -$HOME/.config/ds4/ds4.env --env $HOME/.config/ds4/ds4-spark0.env --strict
$HOME/ds4/scripts/ops_tp3_readiness.sh --self spark0 --env -$HOME/.config/ds4/ds4.env --env $HOME/.config/ds4/ds4-spark0.env --strict
```

Do not change Spark networking as part of automation loops; record proposed firewall/routing changes for human approval.

