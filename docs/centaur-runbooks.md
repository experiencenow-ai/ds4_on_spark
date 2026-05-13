# Centaur-on-Spark runbooks (v73)

Entry point for the Centaur v73 smoke + ring rehearsal docs/scripts.

Safety constraints (assumed by all runbooks): no `sudo`, no system services, no secrets, and no model weight downloads.

## Start here

- Spark0 v73 smoke (runs the full command sequence): `docs/centaur-spark0-v73-smoke.md`
- Latest smoke + ring status (evidence bundles + ring-rsync TODO): `docs/centaur-smoke-status-20260512.md`
- Bug report workflow + sanitization checklist: `docs/centaur-bug-report.md`
- PR checklist/template (required sections for automation PRs): `docs/centaur-pr-checklist.md`

## Spark0 smoke (recommended)

From your Mac (repo root):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export CENTAUR_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>
```

Mac-side prerequisites for the helper scripts: `ssh` plus `rsync` (preferred) or `scp` (fallback).

The evidence helper runs:

- stage + smoke (Spark0)
- Spark0 artifact validation
- Mac-side artifact fetch into `/private/tmp/centaur-smoke/spark0-v73/<run_id>/` (or `/tmp/...`)

If you prefer running the pieces manually, see `docs/centaur-spark0-v73-smoke.md`.

After a manual run, validate that expected outputs exist (run on Spark0):

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_RUN_ID=...; sh -s" < ./scripts/centaur_spark0_v73_validate_artifacts.sh
```

To fetch a small sanitized artifact bundle (log + manifests + dashboard) back to your Mac:

```bash
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"
```

To promote a fetched bundle into a commit-ready fixtures directory (after review/redaction):

```bash
sh ./scripts/centaur_spark0_v73_fixture_pack.sh "$CENTAUR_RUN_ID"
```

Optional (Mac-side): capture zip facts without extracting (useful for bug reports):

```bash
sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip
```

## Spark1/Spark2 (3-node ring total)

If you only have Spark1/Spark2 (3 nodes total including Spark0), use:

- `docs/centaur-ring-spark12.md`

That runbook includes:

- an end-to-end “Quickstart” (Spark0 smoke → Spark1/2 setup → ring rsync → artifact fetch)
- a safe SSH mesh preflight (Spark0↔Spark1↔Spark2) using `scripts/ops_spark_ring_mesh_check.sh` (recommended before rsync ring-step)
- staging `centaur_spec_impl_v73.zip` to Spark1/2
- per-node setup via `scripts/centaur_spark_v73_node_setup.sh`
- Spark0-local ring sim (`hyor-ring-step` across multiple local roots)
- rsync-staged “real ring” (no shared filesystem) + optional HTTP transport

## Spark1/Spark2/Spark3 (4-node total)

If you also have Spark3, use:

- `docs/centaur-ring-spark123.md`

## Scripts (what’s where)

- Spark0 smoke:
  - `scripts/centaur_spark0_v73_run.sh` (Mac-side wrapper)
  - `scripts/centaur_spark0_v73_stage.sh` (stages zip + fixture + smoke helpers)
  - `scripts/centaur_spark0_v73_smoke.sh` (runs on Spark0)
  - `scripts/centaur_spark0_v73_validate_artifacts.sh` (runs on Spark0)
  - `scripts/centaur_spark0_v73_fetch_artifacts.sh` (Mac-side fetch helper)
  - `scripts/centaur_spark0_v73_bundle_validate.sh` (Mac-side validation for fetched bundles)
  - `scripts/centaur_spark0_v73_smoke_report.sh` (generates a PR/issue-ready Markdown summary from a fetched bundle)
  - `scripts/centaur_spark0_v73_fixture_pack.sh` (packs a fetched bundle into repo fixtures)
- Spark1/2 ring:
  - `scripts/centaur_spark12_v73_stage.sh`
  - `scripts/centaur_spark12_v73_node_setup_run.sh` (Mac-side wrapper)
  - `scripts/centaur_spark12_v73_node_setup_fetch_logs.sh` (Mac-side fetch helper: log + facts + freeze)
  - `scripts/centaur_spark_ring_sim_spark12_v73.sh`
  - `scripts/centaur_spark12_v73_ring_sim_run.sh` (Mac-side wrapper)
  - `scripts/centaur_spark12_v73_ring_sim_evidence_run.sh` (Mac-side one-command evidence helper)
  - `scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh` (Mac-side fetch helper)
  - `scripts/centaur_spark12_v73_ring_bundle_validate.sh` (Mac-side validation for fetched ring bundles)
  - `scripts/centaur_spark12_v73_ring_sim_fixture_pack.sh` (packs a fetched bundle into repo fixtures)
  - `scripts/centaur_spark_ring_rsync_spark12_v73.sh`
  - `scripts/centaur_spark12_v73_ring_rsync_run.sh` (Mac-side wrapper)
  - `scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh` (Mac-side one-command evidence helper)
  - `scripts/centaur_spark12_v73_ring_rsync_remote_verify.sh` (Mac-side Spark1/2 `hyor-sync-status` verifier)
  - `scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh` (Mac-side fetch helper)
  - `scripts/centaur_spark12_v73_ring_rsync_fixture_pack.sh` (packs a fetched bundle into repo fixtures)
  - `scripts/centaur_spark12_v73_validate_ring_artifacts.sh` (runs on orchestrator host)
  - `scripts/centaur_spark_v73_node_setup_run.sh` (single-node wrapper; Spark1/Spark2/etc)
- Optional HTTP transport helpers:
  - `scripts/centaur_spark_hyor_controller_http_v73.sh`
  - `scripts/centaur_spark_hyor_agent_http_v73.sh`
  - `scripts/centaur_spark_hyor_node_discover_v73.sh`
  - Notes:
    - For controller-root selection, prefer `RING_WORKDIR` + `RING_RUN_ID` (ring rsync) or `CENTAUR_WORKDIR` (Spark0 smoke); override with `HYOR_CONTROLLER_ROOT` if needed.

## Fixtures

- Tiny synthetic model catalog used by the Spark0 smoke:
  - `fixtures/centaur-smoke/spark0-v73/unit_model_catalog.json`
