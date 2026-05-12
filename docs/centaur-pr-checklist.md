# Centaur-on-Spark PR checklist (automation-ready)

Use this as a copy/paste template for PR bodies touching Centaur-on-Spark runbooks/scripts.

Constraints: no `sudo`, no system services, no secrets, and no model weight downloads.

## Summary

- What changed and why (1-3 bullets).

## Verification

- Local (Mac):
  - `sh -n scripts/centaur_spark*.sh`
- Spark (only if you actually ran it):
  - Spark0 smoke: `docs/centaur-spark0-v73-smoke.md`
  - Spark1/2 ring: `docs/centaur-ring-spark12.md`

## Spark commands run

Paste exact commands (sanitized), including:

- Hostnames (redact if needed) and users (e.g. `spark0@<spark0-host>`)
- Working directories (`pwd`) and run ids (`CENTAUR_RUN_ID`, `RING_RUN_ID`)
- Paths used (`CENTAUR_ZIP`, `CENTAUR_WORKDIR`, `remote_base_dir`)

Example (Spark0 smoke, from Mac):

```bash
export SSH_OPTS="..."
sh ./scripts/centaur_spark0_v73_run.sh spark0@<spark0-host>
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"
```

Example (Spark1/2 ring rsync, from Mac):

```bash
export SSH_OPTS="..."
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_ring_rsync_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host> "$RING_RUN_ID"
sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
```

## Centaur smoke status (Spark0 v73)

- Status: PASS | FAIL | NOT RUN
- Run id: `<CENTAUR_RUN_ID>`
- Zip facts: `zip_sha256`, zip `mtime`, `decomposer_version`
- Deps: `python3 -V`, `pip freeze` excerpt (at least numpy/scipy/scikit-learn)
- Artifacts: `effective_manifests/`, `hyor_effective/`, `hyor_dashboard/`, `smoke.log`

Tip: `scripts/centaur_spark0_v73_fetch_artifacts.sh` is the preferred sanitized bundle.
Tip: `sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip` captures zip facts without extracting.

## Centaur dev bug report notes

If anything failed, classify it explicitly:

- **Centaur bug**: parser/schema/state failures inside `centaur.py` commands, including `selftest`.
- **DS4 runtime bug**: host deps/layout/perms (missing `python3`, missing `unzip`, missing wheels, etc).

For the shared checklist and sanitization rules, follow:

- `docs/centaur-bug-report.md`

## Three-node ring readiness (Spark0 + Spark1 + Spark2)

- Status: READY | PARTIAL | NOT RUN
- Ring mode: `ring_sim_spark12` | `ring_rsync_spark12`
- Run id: `<RING_RUN_ID>`
- Evidence (sanitized):
  - `effective_manifests/hyor_effective_manifest_spark1.json`
  - `effective_manifests/hyor_effective_manifest_spark2.json`
  - per-node `hyor-sync-status` (controller + spark0 + spark1 + spark2)
  - ring log excerpt (if `RING_LOG` was enabled)

## Risks

- What could break / what assumptions the change relies on.
