# Centaur-on-Spark bug reports (Centaur vs DS4 runtime)

Goal: capture enough context to reproduce a failure without leaking secrets, hostnames, or private network details.

Always classify first:

- **Centaur bug**: a `centaur.py` command fails due to parsing/schema/state/logic (selftest failures, unexpected exceptions, invalid outputs).
- **DS4 runtime bug**: the host/runtime environment prevents Centaur from running (missing `python3`, missing `unzip`, `pip` source-build pain, permissions, filesystem layout).

## Recommended workflow (Spark0 v73 smoke)

1) Run the smoke with a run id so artifacts are isolated:

```bash
export CENTAUR_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark0_v73_run.sh spark0@<spark0-host>
```

2) Fetch a small artifact bundle back to your Mac (no venv, no source tree):

```bash
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"
```

Default local output directory:

- `/private/tmp/centaur-smoke/spark0-v73/<run_id>/` (or `/tmp/...` if `/private/tmp` is unavailable)

## Recommended workflow (Spark1/Spark2 ring rsync)

1) Run the rsync-staged ring-step with a run id so artifacts are isolated:

```bash
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_ring_rsync_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

2) Fetch a small artifact bundle back to your Mac:

```bash
sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
```

Default local output directory:

- `/private/tmp/centaur-ring/spark12-v73/<ring_run_id>/` (or `/tmp/...` if `/private/tmp` is unavailable)

## What to include (both bug types)

- `CENTAUR_RUN_ID` and Spark host (sanitized)
- Full command line used (copy/paste)
- Centaur zip facts:
  - zip path
  - zip `ls -la` (mtime/size)
  - `zip_sha256` (printed by the smoke; also present in `smoke.log`)
  - Optional helper (Mac-side) to capture these facts without extracting:

    ```bash
    sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip
    ```
- Python + deps:
  - `python3 -V`
  - `pip freeze` excerpt (at least `numpy`, `scipy`, `scikit-learn`)
- Failing sub-step:
  - exact `centaur.py ...` command line
  - a bounded tail excerpt (sanitized)

## Artifact bundle contents (Spark0 v73)

The fetch script pulls (when present):

- `smoke.log` (includes package facts + full command outputs)
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
