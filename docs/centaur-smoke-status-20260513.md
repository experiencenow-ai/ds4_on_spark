# Centaur on Spark: v73 smoke + ring status (2026-05-13)

This records the current reproducible Centaur v73 smoke/ring evidence bundles and the runbook state as of **2026-05-13**.

Safety constraints: no `sudo`, no system services, no secrets, and no model weight downloads.

## Inputs

- Centaur zip (Mac-local): `/Users/mac/Downloads/centaur_spec_impl_v73.zip`
  - Canonical zip facts (commit-safe): `fixtures/centaur-smoke/centaur_spec_impl_v73_zip_facts.json`
    - `sha256`: `3d61b1258aac815d294b3c8fdb4e72ac7851e1b47d02a0daff55117f2885af5a`
    - `mtime_utc`: `2026-05-11T02:08:11Z`
    - `decomposer_version`: `centaur-impl-0.68`

## Spark0 v73 smoke (PASS)

Commit-safe evidence bundles:

- `fixtures/centaur-smoke/spark0-v73/20260512T030829Z/`
- `fixtures/centaur-smoke/spark0-v73/20260512T073455Z/`

Runbook + scripts:

- `docs/centaur-spark0-v73-smoke.md`
- `scripts/centaur_spark0_v73_evidence_run.sh`

## Spark12 ring sim (Spark0-local, PASS)

Commit-safe evidence bundles:

- `fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T041207Z/`
- `fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T074400Z/`

Runbook + scripts:

- `docs/centaur-ring-spark12.md`
- `scripts/centaur_spark12_v73_ring_sim_evidence_run.sh`

## Spark12 ring rsync (Spark0 orchestrated, NOT RUN)

Status: the rsync-staged “real ring” path still needs Spark1/Spark2 hardware to be SSH-reachable from the Mac and also reachable from Spark0 (mesh).

Preflight helpers (safe; Mac-side):

- SSH mesh check (Spark0↔Spark1↔Spark2): `scripts/ops_spark_ring_mesh_check.sh`
- `rsync` availability check (required by ring-rsync): `scripts/ops_spark_rsync_check.sh`

Runbook + scripts:

- `docs/centaur-ring-spark12.md`
- `scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh`

Expected commit-safe evidence bundle shape (once run):

- `fixtures/centaur-smoke/spark12-v73/ring_rsync/<RING_RUN_ID>/`
  - `effective_manifests/hyor_effective_manifest_spark1.json`
  - `effective_manifests/hyor_effective_manifest_spark2.json`
  - `ring_rsync.log` (sanitized)

## Bug notes

- Centaur bugs observed: none (based on committed PASS bundles listed above).
- DS4 runtime/host issues observed: none in the committed bundles; ring-rsync remains untested on real Spark1/2 hardware.

