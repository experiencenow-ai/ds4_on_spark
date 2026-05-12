# Spark12 v73 ring sim (Spark0-local): 20260512T074400Z

This is a small, sanitized artifact bundle from a Spark0-local ring simulation
for a 3-node Spark ring (Spark0 + Spark1 + Spark2) using Centaur v73.

Notes:

- This is **not** a networked ring run (no Spark1/2 SSH required); it simulates
  Spark1/2 roots on Spark0 so `hyor-ring-step` can copy objects between peer
  roots on one filesystem.
- No zips, no venvs, no Centaur sources, and no secrets are included.

## Spark commands run (sanitized)

On Spark0 (from Mac; streamed):

```bash
export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/private/tmp/ds4_spark_known_hosts"
export RING_RUN_ID=20260512T074400Z
sh ./scripts/centaur_spark12_v73_ring_sim_run.sh spark0@<spark0-host>
```

Validate artifacts (Spark0):

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export RING_RUN_ID=20260512T074400Z; sh -s -- --mode sim" < ./scripts/centaur_spark12_v73_validate_ring_artifacts.sh
```

Fetch back to this bundle (from Mac):

```bash
sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> 20260512T074400Z "~/centaur-smoke/v73/ring_sim_spark12" fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T074400Z
```

