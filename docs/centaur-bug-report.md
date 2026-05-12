# Centaur-on-Spark bug reports (Centaur vs DS4 runtime)

Goal: capture enough context to reproduce a failure without leaking secrets, hostnames, or private network details.

Always classify first:

- **Centaur bug**: a `centaur.py` command fails due to parsing/schema/state/logic (selftest failures, unexpected exceptions, invalid outputs).
- **DS4 runtime bug**: the host/runtime environment prevents Centaur from running (missing `python3`, missing `unzip`, `pip` source-build pain, permissions, filesystem layout).

## Recommended workflow (Spark0 v73 smoke)

Recommended: run the one-command evidence loop (stage → smoke → validate → fetch):

```bash
export CENTAUR_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>
```

If you already ran the smoke and only want to fetch:

```bash
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"
```

Default local output directory:

- `/private/tmp/centaur-smoke/spark0-v73/<run_id>/` (or `/tmp/...` if `/private/tmp` is unavailable)

## Recommended workflow (Spark1/Spark2 ring rsync)

Recommended: run the one-command evidence loop (optional node setup → ring rsync → validate → fetch):

```bash
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

If you already ran the ring rsync and only want to fetch:

```bash
sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
```

Default local output directory:

- `/private/tmp/centaur-ring/spark12-v73/<ring_run_id>/` (or `/tmp/...` if `/private/tmp` is unavailable)

## Recommended workflow (Spark12 ring sim)

Recommended: run the one-command evidence loop (run → validate → fetch):

```bash
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host>
```

If you already ran the ring sim and only want to fetch:

```bash
sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
```

Default local output directory:

- `/private/tmp/centaur-ring-sim/spark12-v73/<ring_run_id>/` (or `/tmp/...` if `/private/tmp` is unavailable)

## What to include (both bug types)

- `CENTAUR_RUN_ID` and Spark host (sanitized)
- Full command line used (copy/paste)
- Centaur zip facts:
  - zip path
  - zip `ls -la` (mtime/size)
  - `zip_sha256` (printed by the smoke; also present in `smoke.log`)
- Python + deps:
  - `python3 -V`
  - `pip freeze` excerpt (at least `numpy`, `scipy`, `scikit-learn`) or the full `pip_freeze.txt`
- Failing sub-step:
  - exact `centaur.py ...` command line
  - a bounded tail excerpt (sanitized)

## Artifact bundle contents (Spark0 v73)

The fetch script pulls (when present):

- `smoke.log` (includes package facts + full command outputs)
- `smoke_facts.json` (structured zip/python/pip/requirements facts)
- `pip_freeze.txt` (sanitized dependency versions)
- `effective_manifests/` (includes `hyor_effective_manifest_spark0.json`)
- `hyor_effective/spark0/` (materialized node view)
- `hyor_dashboard/` (HTML/JSON dashboard output)

These are generally safe to share after sanitizing hostnames and private paths.

## Artifact bundle contents (Spark1/Spark2 ring rsync)

The fetch script pulls (when present):

- `ring_rsync.log`
- `effective_manifests/` (includes `hyor_effective_manifest_spark1.json` and `..._spark2.json`)

## Sanitization checklist

Do not paste/commit:

- tokens, API keys, private keys
- raw SSH host keys
- private IPs/MACs or internal hostnames (replace with `<redacted-host>`)
- absolute paths that include usernames when posting publicly

When in doubt, share `smoke.log` only after manual review and redaction.
