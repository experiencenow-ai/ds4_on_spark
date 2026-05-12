# Spark12 v73 ring sim (Spark0-local): 20260512T041207Z

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
export CENTAUR_ROOT=~/centaur-smoke/v73/run/20260512T030829Z/centaur_spec_impl_v73
export CENTAUR_VENV=~/centaur-smoke/v73/run/20260512T030829Z/venv
export SPARK_NODE_COUNT=3
export RING_RUN_ID=20260512T041207Z
export RING_WORKDIR=~/centaur-smoke/v73/ring_sim_spark12
export RING_LOG=~/centaur-smoke/v73/ring_sim_spark12/run/$RING_RUN_ID/ring_sim.log
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_ROOT=\"$CENTAUR_ROOT\" CENTAUR_VENV=\"$CENTAUR_VENV\" SPARK_NODE_COUNT=\"$SPARK_NODE_COUNT\" RING_RUN_ID=\"$RING_RUN_ID\" RING_WORKDIR=\"$RING_WORKDIR\" RING_LOG=\"$RING_LOG\"; sh -s" < ./scripts/centaur_spark_ring_sim_v73.sh
```

Fetch back to this bundle (from Mac):

```bash
sh ./scripts/centaur_spark12_v73_ring_sim_fetch_artifacts.sh spark0@<spark0-host> 20260512T041207Z "~/centaur-smoke/v73/ring_sim_spark12" fixtures/centaur-smoke/spark12-v73/ring_sim/20260512T041207Z
```
