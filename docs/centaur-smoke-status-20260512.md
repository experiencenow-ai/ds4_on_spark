# Centaur on Spark: v73 smoke + ring sim status (2026-05-12)

This records one reproducible Spark0 v73 smoke run and one Spark0-local 3-node
ring simulation run using the Centaur spec-impl v73 zip.

Safety constraints: no `sudo`, no system services, no secrets, and no model
weight downloads.

## Inputs

- Centaur zip (Mac-local): `/Users/mac/Downloads/centaur_spec_impl_v73.zip`
  - mtime/size: `-rw-r--r--@ 1 mac  staff  385391 May 11 02:08 /Users/mac/Downloads/centaur_spec_impl_v73.zip`
  - `zip_sha256`: `3d61b1258aac815d294b3c8fdb4e72ac7851e1b47d02a0daff55117f2885af5a`
  - `decomposer_version`: `centaur-impl-0.68`

## Spark0 v73 smoke (PASS)

- Spark0 host (mDNS): `aitopatom-9ab9.local`
- Spark0 OS/kernel: `Linux 6.17.0-1014-nvidia` (`aarch64`, Ubuntu)
- Spark0 python: `Python 3.12.3`
- Pip deps (from log): `numpy==2.4.4`, `scipy==1.17.1`, `scikit-learn==1.8.0`

Spark commands run (from Mac; staged zip + streamed smoke):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export CENTAUR_RUN_ID=20260512T073455Z
sh ./scripts/centaur_spark0_v73_run.sh spark0@aitopatom-9ab9.local
ssh $SSH_OPTS spark0@aitopatom-9ab9.local "export CENTAUR_RUN_ID=20260512T073455Z; sh -s" < ./scripts/centaur_spark0_v73_validate_artifacts.sh
sh ./scripts/centaur_spark0_v73_fetch_artifacts.sh spark0@aitopatom-9ab9.local 20260512T073455Z
```

Sanitized bundle (commit-safe):

- `fixtures/centaur-smoke/spark0-v73/20260512T073455Z/`

## Spark12 ring sim (Spark0-local, PASS)

Spark commands run (from Mac; streamed):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export RING_RUN_ID=20260512T074400Z
sh ./scripts/centaur_spark12_v73_ring_sim_run.sh spark0@aitopatom-9ab9.local
ssh $SSH_OPTS spark0@aitopatom-9ab9.local "export RING_RUN_ID=20260512T074400Z; sh -s -- --mode sim" < ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh
sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@aitopatom-9ab9.local 20260512T074400Z
```

Sanitized bundle (commit-safe):

- `fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T074400Z/`

## Bug notes

- Centaur bugs observed: none in these runs (selftest + HyoR + provider/catalog + benchmark + dashboard all PASS).
- DS4 runtime/host issues observed: none (wheels were available; no source builds).

