# Centaur on Spark: v73 smoke + ring sim status (2026-05-12)

This records reproducible Spark0 v73 smoke runs and Spark0-local 3-node ring
simulation runs using the Centaur spec-impl v73 zip.

Safety constraints: no `sudo`, no system services, no secrets, and no model
weight downloads.

## Inputs

- Centaur zip (Mac-local): `/Users/mac/Downloads/centaur_spec_impl_v73.zip`
  - Canonical zip facts (commit-safe): `fixtures/centaur-smoke/centaur_spec_impl_v73_zip_facts.json`

## Spark0 v73 smoke (PASS)

- Spark0 host (mDNS): `aitopatom-9ab9.local`
- Spark0 OS/kernel: `Linux 6.17.0-1014-nvidia` (`aarch64`, Ubuntu)
- Spark0 python: `Python 3.12.3`
- Pip deps (from log): `numpy==2.4.4`, `scipy==1.17.1`, `scikit-learn==1.8.0`

Spark commands run (from Mac; staged zip + streamed smoke):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export CENTAUR_RUN_ID=20260512T073455Z
sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@aitopatom-9ab9.local
```

Sanitized bundle (commit-safe):

- `fixtures/centaur-smoke/spark0-v73/20260512T073455Z/`

Re-verified run (not checked in; artifacts fetched locally):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export CENTAUR_RUN_ID=20260512T093838Z
sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@aitopatom-9ab9.local "~/centaur-smoke/v73" /private/tmp/centaur-smoke/spark0-v73/20260512T093838Z
```

Local bundle path:

- `/private/tmp/centaur-smoke/spark0-v73/20260512T093838Z/`

Note: if you pass `remote_dir` explicitly, quote paths like `"~/centaur-smoke/v73"` so your local shell doesn’t expand `~` into a Mac-only `/Users/...` path before SSH.

Re-verified run (not checked in; artifacts fetched locally):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export CENTAUR_RUN_ID=20260512T110824Z
sh ./scripts/centaur_spark0_v73_evidence_run.sh spark0@aitopatom-9ab9.local "~/centaur-smoke/v73" /private/tmp/centaur-smoke/spark0-v73/20260512T110824Z
```

Local bundle path:

- `/private/tmp/centaur-smoke/spark0-v73/20260512T110824Z/`

## Spark12 ring sim (Spark0-local, PASS)

Spark commands run (from Mac; streamed):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export RING_RUN_ID=20260512T074400Z
sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@aitopatom-9ab9.local
```

Sanitized bundle (commit-safe):

- `fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T074400Z/`

Re-verified run (not checked in; artifacts fetched locally):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export RING_RUN_ID=20260512T094444Z
sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@aitopatom-9ab9.local "~/centaur-smoke/v73/ring_sim_spark12" /private/tmp/centaur-ring-sim/spark12-v73/20260512T094444Z
```

Local bundle path:

- `/private/tmp/centaur-ring-sim/spark12-v73/20260512T094444Z/`

Re-verified run (not checked in; artifacts fetched locally):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export RING_RUN_ID=20260512T111132Z
sh ./scripts/centaur_spark12_v73_ring_sim_evidence_run.sh spark0@aitopatom-9ab9.local "~/centaur-smoke/v73/ring_sim_spark12" /private/tmp/centaur-ring-sim/spark12-v73/20260512T111132Z
```

Local bundle path:

- `/private/tmp/centaur-ring-sim/spark12-v73/20260512T111132Z/`

## Spark12 ring rsync (Spark0 orchestrated, NOT RUN)

As of `2026-05-12`, Spark1/Spark2 were not reachable from the Mac environment
(`spark1.local`/`spark2.local` DNS failures were observed in the probe runbook),
so the rsync-staged “real ring” path has not been executed yet.

When Spark1/Spark2 hardware exists and is SSH-reachable, run the full 3-node
ring path (Mac-driven). Recommended: one-command evidence loop (node setup → ring rsync → validate → fetch):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_ring_rsync_evidence_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
```

To skip node setup (when Spark1/2 are already set up), set:

```bash
export RING_SKIP_NODE_SETUP=1
```

If you prefer running the pieces manually, use:

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"

# 1) Per-node setup on Spark1/2 (stages zip + creates venv + runs selftest)
export NODE_SETUP_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_node_setup_run.sh spark1@<spark1-host> spark2@<spark2-host> "~/centaur-smoke/v73" "$NODE_SETUP_RUN_ID"
sh ./scripts/centaur_spark12_v73_node_setup_fetch_logs.sh spark1@<spark1-host> spark2@<spark2-host> "$NODE_SETUP_RUN_ID" "~/centaur-smoke/v73"

# 2) Rsync-staged ring-step orchestrated from Spark0 (stages zip to Spark1/2 by default)
export RING_RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
sh ./scripts/centaur_spark12_v73_ring_rsync_run.sh spark0@<spark0-host> spark1@<spark1-host> spark2@<spark2-host>
ssh $SSH_OPTS spark0@<spark0-host> "export RING_RUN_ID=\"$RING_RUN_ID\"; sh -s -- --mode rsync" < ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh
sh ./scripts/centaur_spark12_v73_ring_rsync_fetch_artifacts.sh spark0@<spark0-host> "$RING_RUN_ID"
```

Expected Spark0 remote log path:

- `~/centaur-smoke/v73/ring_rsync_spark12/run/<ring_run_id>/ring_rsync.log`

Expected local fetch path (default):

- `/private/tmp/centaur-ring/spark12-v73/<ring_run_id>/`

Record the run id + sanitized `effective_manifests/` evidence in the next
Centaur status file update.

## Bug notes

- Centaur bugs observed: none in these runs (selftest + HyoR + provider/catalog + benchmark + dashboard all PASS).
- DS4 runtime/host issues observed: none (wheels were available; no source builds).
