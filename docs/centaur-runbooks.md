# Centaur-on-Spark runbooks (v73)

> Supersedes: `docs/centaur-runbooks.md`, `docs/centaur-bug-report.md`, `docs/centaur-pr-checklist.md`, `docs/centaur-ring-spark12.md`, `docs/centaur-ring-spark123.md`, `docs/centaur-smoke-status-20260512.md`, `docs/centaur-smoke-status-20260513.md`, `docs/centaur-spark0-v73-smoke.md`, `docs/centaur-ds4-prefix-kv-contract.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 9 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `centaur-runbooks.md`: Centaur-on-Spark runbooks (v73) (127 lines).
- `centaur-bug-report.md`: Centaur-on-Spark bug reports (Centaur vs DS4 runtime) (157 lines).
- `centaur-pr-checklist.md`: Centaur-on-Spark PR checklist (automation-ready) (91 lines).
- `centaur-ring-spark12.md`: Centaur HyoR ring rehearsal: Spark1/Spark2 (3-node ring prep + runbook) (539 lines).
- `centaur-ring-spark123.md`: Example Centaur HyoR ring rehearsal: Spark1/Spark2/Spark3 (238 lines).
- `centaur-smoke-status-20260512.md`: Centaur on Spark: v73 smoke + ring sim status (2026-05-12) (149 lines).
- `centaur-smoke-status-20260513.md`: Centaur on Spark: v73 smoke + ring status (2026-05-13) (80 lines).
- `centaur-spark0-v73-smoke.md`: Centaur on Spark0: spec-impl v73 smoke (reproducible) (293 lines).
- `centaur-ds4-prefix-kv-contract.md`: Centaur / DS4 Prefix KV Contract (153 lines).

## Command Inventory

- `centaur-runbooks.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>`
- `centaur-runbooks.md`: `ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_RUN_ID=...; sh -s" < ./scripts/centaur_spark0_v73_validate_artifacts.sh`
- `centaur-runbooks.md`: `sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"`
- `centaur-runbooks.md`: `sh ./scripts/centaur_spark0_v73_fixture_pack.sh "$CENTAUR_RUN_ID"`
- `centaur-runbooks.md`: `sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark0_v73_smoke_report.sh "$CENTAUR_RUN_ID" "$bundle_dir" "$bundle_dir/smoke_report.md"`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_report.sh "$RING_RUN_ID" "$bundle_dir" "$bundle_dir/ring_rsync_report.md"`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host>`
- `centaur-bug-report.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"`
- `centaur-pr-checklist.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>`
- `centaur-pr-checklist.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-pr-checklist.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host>`
- `centaur-ring-spark12.md`: `./scripts/centaur_spark_v73_prereqs_check.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-ring-spark12.md`: `./scripts/ops_spark_ring_mesh_check.sh --topology ring spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-ring-spark12.md`: `./scripts/ops_spark_rsync_check.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host>`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_run.sh spark0@<spark0-host>`
- `centaur-ring-spark12.md`: `ssh $SSH_OPTS spark0@<spark0-host> "export RING_RUN_ID=\"$RING_RUN_ID\"; sh -s -- --mode sim" < ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_fixture_pack.sh "$RING_RUN_ID"`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark12_v73_node_setup_run.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73" "$NODE_SETUP_RUN_ID"`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark12_v73_node_setup_fetch_logs.sh spark1@<spark1-host> spark2@<spark2-host> "$NODE_SETUP_RUN_ID" "~/centaur-smoke/v73"`
- `centaur-ring-spark12.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-ring-spark123.md`: `sh ./scripts/centaur_spark_v73_stage.sh spark1@<spark1-host> "~/centaur-smoke/v73"`
- `centaur-ring-spark123.md`: `sh ./scripts/centaur_spark_v73_stage.sh spark2@<spark2-host> "~/centaur-smoke/v73"`
- `centaur-ring-spark123.md`: `sh ./scripts/centaur_spark_v73_stage.sh spark3@<spark3-host> "~/centaur-smoke/v73"`
- `centaur-ring-spark123.md`: `ssh $SSH_OPTS spark1@<spark1-host> "cd ~/centaur-smoke/v73 && export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip && export CENTAUR_LOG=~/centaur-smoke/v73/run/node_setup_spark1.log && sh -s" < ./scripts/centaur_spark_v73_node_setup.sh`
- `centaur-ring-spark123.md`: `ssh $SSH_OPTS spark2@<spark2-host> "cd ~/centaur-smoke/v73 && export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip && export CENTAUR_LOG=~/centaur-smoke/v73/run/node_setup_spark2.log && sh -s" < ./scripts/centaur_spark_v73_node_setup.sh`
- `centaur-ring-spark123.md`: `ssh $SSH_OPTS spark3@<spark3-host> "cd ~/centaur-smoke/v73 && export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip && export CENTAUR_LOG=~/centaur-smoke/v73/run/node_setup_spark3.log && sh -s" < ./scripts/centaur_spark_v73_node_setup.sh`
- `centaur-ring-spark123.md`: `python3 -m venv ./venv`
- `centaur-ring-spark123.md`: `./venv/bin/python3 -m pip install -r ./centaur_spec_impl_v73/requirements.txt`
- `centaur-ring-spark123.md`: `./venv/bin/python3 -u ./centaur_spec_impl_v73/centaur.py selftest --json`
- `centaur-ring-spark123.md`: `sh ./scripts/centaur_spark_ring_sim_v73.sh | tee ~/centaur-smoke/v73/ring_sim/ring_sim.log`
- `centaur-ring-spark123.md`: `ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- spark1@<spark1-host> spark2@<spark2-host> spark3@<spark3-host>" < ./scripts/centaur_spark_ring_rsync_v73.sh`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host> "~/centaur-smoke/v73" /private/tmp/centaur-smoke/spark0-v73/20260512T093838Z`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host> "~/centaur-smoke/v73" /private/tmp/centaur-smoke/spark0-v73/20260512T110824Z`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host>`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host> "~/centaur-smoke/v73/ring_sim_spark12" /private/tmp/centaur-ring-sim/spark12-v73/20260512T094444Z`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@<spark0-host> "~/centaur-smoke/v73/ring_sim_spark12" /private/tmp/centaur-ring-sim/spark12-v73/20260512T111132Z`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_node_setup_run.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73" "$NODE_SETUP_RUN_ID"`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_node_setup_fetch_logs.sh spark1@<spark1-host> spark2@<spark2-host> "$NODE_SETUP_RUN_ID" "~/centaur-smoke/v73"`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-smoke-status-20260512.md`: `ssh $SSH_OPTS spark0@<spark0-host> "export RING_RUN_ID=\"$RING_RUN_ID\"; sh -s -- --mode rsync" < ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh`
- `centaur-smoke-status-20260512.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"`
- `centaur-smoke-status-20260513.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>`
- `centaur-smoke-status-20260513.md`: `sh ./scripts/centaur_spark12_v73_ring_rsync_fixture_pack.sh "$RING_RUN_ID"`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_v73_zip_facts.sh /Users/mac/Downloads/centaur_spec_impl_v73.zip`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@<spark0-host>`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_spark0_v73_run.sh spark0@<spark0-host>`
- `centaur-spark0-v73-smoke.md`: `./scripts/centaur_spark0_v73_stage.sh spark0@<spark0-host>`
- `centaur-spark0-v73-smoke.md`: `ssh $SSH_OPTS spark0@<spark0-host> 'cd ~/centaur-smoke/v73 && export CENTAUR_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)" && export CENTAUR_LOG=~/centaur-smoke/v73/run/"$CENTAUR_RUN_ID"/smoke.log && export CENTAUR_ZIP=~/centaur-smoke/v73/centaur_spec_impl_v73.zip && export CENTAUR_CATALOG_JSON=~/centaur-smoke/v73/unit_model_catalog.json && sh ./centaur_spark0_v73_smoke.sh'`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_spark0_v73_validate_artifacts.sh`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@<spark0-host> "$CENTAUR_RUN_ID"`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_spark0_v73_bundle_validate.sh "$CENTAUR_RUN_ID" "$bundle_dir"`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_spark0_v73_smoke_report.sh "$CENTAUR_RUN_ID" "$bundle_dir" "$bundle_dir/smoke_report.md"`
- `centaur-spark0-v73-smoke.md`: `sh ./scripts/centaur_spark0_v73_fixture_pack.sh "$CENTAUR_RUN_ID"`
- `centaur-spark0-v73-smoke.md`: `ssh ... "cd ... && sh -s" < ./scripts/centaur_spark0_v73_smoke.sh`
- `centaur-spark0-v73-smoke.md`: `sha256: <zip_sha256>`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/centaur-runbooks.md` | 127 | Centaur-on-Spark runbooks (v73) | Start here, Spark0 smoke (recommended), Spark1/Spark2 (3-node ring total), Spark1/Spark2/Spark3 (4-node total), Scripts (what’s where) |
| `docs/centaur-bug-report.md` | 157 | Centaur-on-Spark bug reports (Centaur vs DS4 runtime) | Recommended workflow (Spark0 v73 smoke), Recommended workflow (Spark1/Spark2 ring rsync), Recommended workflow (Spark12 ring sim), What to include (both bug types), Artifact bundle contents (Spark0 v73) |
| `docs/centaur-pr-checklist.md` | 91 | Centaur-on-Spark PR checklist (automation-ready) | Summary, Verification, Spark commands run, Centaur smoke status (Spark0 v73), Centaur dev bug report notes |
| `docs/centaur-ring-spark12.md` | 539 | Centaur HyoR ring rehearsal: Spark1/Spark2 (3-node ring prep + runbook) | Topology (3-node ring), Quickstart (recommended order), Spark1/Spark2 bring-up checklist (when hardware exists), Prereqs (run once on Spark0), Run the Spark0-local ring sim (example: Spark0/1/2) |
| `docs/centaur-ring-spark123.md` | 238 | Example Centaur HyoR ring rehearsal: Spark1/Spark2/Spark3 | Spark1/Spark2/Spark3 bring-up checklist (when hardware exists), Prereqs (run once on Spark0), Run the Spark0-local ring sim, What to record for “ring readiness”, Next step (when Spark1/2/3 hardware exists) |
| `docs/centaur-smoke-status-20260512.md` | 149 | Centaur on Spark: v73 smoke + ring sim status (2026-05-12) | Inputs, Spark0 v73 smoke (PASS), Spark12 ring sim (Spark0-local, PASS), Spark12 ring rsync (Spark0 orchestrated, NOT RUN), Bug notes |
| `docs/centaur-smoke-status-20260513.md` | 80 | Centaur on Spark: v73 smoke + ring status (2026-05-13) | Inputs, Spark0 v73 smoke (PASS), Spark12 ring sim (Spark0-local, PASS), Spark12 ring rsync (Spark0 orchestrated, NOT RUN), Bug notes |
| `docs/centaur-spark0-v73-smoke.md` | 293 | Centaur on Spark0: spec-impl v73 smoke (reproducible) | Inputs, Package facts (captured by the smoke), Quickstart (recommended), What the smoke actually runs, Capturing a smoke report (sanitized) |
| `docs/centaur-ds4-prefix-kv-contract.md` | 153 | Centaur / DS4 Prefix KV Contract | KV Semantics, Recommended Centaur Shape, DS4 Prefix Manifest V1, Context Packet V1, DS4 Runtime API Sketch |
