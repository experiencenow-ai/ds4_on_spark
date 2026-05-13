# Spark0/Spark1/Spark2 Layout Manifest (TP=3 Prep)

This directory provides a **human review** mapping from this repo’s deploy assets to recommended on-host locations for a three-node Spark inventory (`spark0`, `spark1`, `spark2`).

Prefer the staging + install wrappers:

- Mac-side staging: `./scripts/ops_stage_spark_ring.sh --topology ring ...`
- Spark-side install: `sudo /tmp/ds4-scripts/ops_install_staged_assets.sh --instance <spark0|spark1|spark2> ...`

The manifests here are intended for:

- review (“what ends up where?”)
- packaging discussions (future)
- spot-checking an existing host layout

Files:

- `system.manifest.tsv` — system units + `/etc` + `/opt` layout (human-run install)
- `user.manifest.tsv` — `systemd --user` layout under `~/.config` + `~/.config/ds4/`

Notes:

- Do not commit secrets; treat all `.env`/`.conf` copies as local host state.
- For TP=3, prefer `deploy/config/ds4-spark*.tp3.env.example` as the starting env per rank.
- Use the strict-start gates when appropriate:
  - TP=2: `ds4-tp2-strict@%i.service`
  - TP=3: `ds4-tp3-strict@%i.service`
  - TP=2 → TP=3 transition (preflight only): `ds4-preflight-tp23@%i.service`
