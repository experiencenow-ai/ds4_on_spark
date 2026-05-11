# Centaur-on-Spark runbooks (v73)

Entry point for the Centaur v73 smoke + ring rehearsal docs/scripts.

Safety constraints (assumed by all runbooks): no `sudo`, no system services, no secrets, and no model weight downloads.

## Start here

- Spark0 v73 smoke (runs the full command sequence): `docs/centaur-spark0-v73-smoke.md`
- Bug report workflow + sanitization checklist: `docs/centaur-bug-report.md`
- PR checklist/template (required sections for automation PRs): `docs/centaur-pr-checklist.md`

## Spark0 smoke (recommended)

From your Mac (repo root):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
sh ./scripts/centaur_spark0_v73_run.sh spark0@<spark0-host>
```

To capture “zip facts” for bug reports (without extracting the zip):

```bash
sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip
```

After the run, validate that expected outputs exist (run on Spark0):

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_RUN_ID=...; sh -s" < ./scripts/centaur_spark0_v73_validate_artifacts.sh
```

To fetch a small sanitized artifact bundle (log + manifests + dashboard) back to your Mac:

```bash
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"
```

## Spark1/Spark2 (3-node ring total)

If you only have Spark1/Spark2 (3 nodes total including Spark0), use:

- `docs/centaur-ring-spark12.md`

That runbook includes:

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
  - `scripts/centaur_spark0_v73_stage.sh` (stages zip + fixture)
  - `scripts/centaur_spark0_v73_smoke.sh` (runs on Spark0)
  - `scripts/centaur_spark0_v73_validate_artifacts.sh` (runs on Spark0)
  - `scripts/centaur_spark0_v73_fetch_artifacts.sh` (Mac-side fetch helper)
- Spark1/2 ring:
  - `scripts/centaur_spark12_v73_stage.sh`
  - `scripts/centaur_spark_ring_sim_spark12_v73.sh`
  - `scripts/centaur_spark_ring_rsync_spark12_v73.sh`
  - `scripts/centaur_spark12_v73_ring_rsync_run.sh` (Mac-side wrapper)
  - `scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh` (Mac-side fetch helper)
- Optional HTTP transport helpers:
  - `scripts/centaur_spark_hyor_controller_http_v73.sh`
  - `scripts/centaur_spark_hyor_agent_http_v73.sh`
  - `scripts/centaur_spark_hyor_node_discover_v73.sh`

## Fixtures

- Tiny synthetic model catalog used by the Spark0 smoke:
  - `fixtures/centaur-smoke/spark0-v73/unit_model_catalog.json`
