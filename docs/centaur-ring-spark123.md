# Centaur HyoR ring rehearsal: Spark1/Spark2/Spark3 (prep + runbook)

Goal: prepare repeatable Spark1/Spark2/Spark3 ring steps **without needing extra hardware yet**, then provide a first “real ring” path once Spark1/2/3 exist.

Important limitation: `centaur.py hyor-ring-step` and `hyor-broadcast-step` require the peer roots to be **local writable paths** (they copy manifests/objects directly between roots). Until we have a shared filesystem between Sparks (or a wrapper that stages peer roots via rsync), the ring work is rehearsed as a **multi-root simulation on Spark0**.

## Prereqs (run once on Spark0)

Run the Spark0 v73 smoke first so you have an extracted Centaur tree + venv:

- `docs/centaur-spark0-v73-smoke.md`

After the smoke, you should have:

- `~/centaur-smoke/v73/run/centaur_spec_impl_v73/centaur.py`
- `~/centaur-smoke/v73/run/venv/bin/python3`

## Run the Spark0-local ring sim

On Spark0:

```bash
export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73
export CENTAUR_VENV=~/centaur-smoke/v73/run/venv
sh ./scripts/centaur_spark_ring_sim_v73.sh | tee ~/centaur-smoke/v73/ring_sim/ring_sim.log
```

This creates four Centaur roots under:

- `~/centaur-smoke/v73/ring_sim/controller`
- `~/centaur-smoke/v73/ring_sim/spark0`
- `~/centaur-smoke/v73/ring_sim/spark1`
- `~/centaur-smoke/v73/ring_sim/spark2`
- `~/centaur-smoke/v73/ring_sim/spark3`

And then exercises, for Spark1/Spark2/Spark3:

- `hyor-sync-init` with left/right peer roots
- `hyor-ring-step --scope metadata`
- `hyor-ring-step --scope effective`
- `hyor-sync-apply` materialization to `~/centaur-smoke/v73/ring_sim/effective/spark{1,2,3}`

## What to record for “ring readiness”

Capture these outputs (sanitized) after the sim:

- `ls -la ~/centaur-smoke/v73/ring_sim/effective/spark1`
- `ls -la ~/centaur-smoke/v73/ring_sim/effective/spark2`
- `ls -la ~/centaur-smoke/v73/ring_sim/effective/spark3`
- `python3 -u centaur.py hyor-sync-status` for each root (controller + spark0..spark3)

## Next step (when Spark1/2/3 hardware exists)

Decide one of:

- shared filesystem for Centaur roots (so peer roots are real paths), or
- a wrapper that stages peer roots via `rsync` into a local temp dir, runs `hyor-ring-step`, then rsyncs the mutated peer root back (needs careful conflict handling because ring-step writes both sides).

Until one of those exists, treat the ring sim as “API/format readiness”, not as a networked deployment.

## “Real ring” option A (recommended for now): rsync-staged ring-step from Spark0

If Spark1/Spark2/Spark3 hardware exists but there is still **no shared filesystem**, use:

- `scripts/centaur_spark_ring_rsync_v73.sh`

This script runs on Spark0 (or any orchestrator with SSH reachability to Spark1/2/3) and:

1. Pulls `hyor/node_spark{1,2,3}` roots from the remote Sparks into a local workdir
2. Runs `hyor-sync-init` + `hyor-sync-publish` + `hyor-ring-step` (metadata + effective) locally across those roots
3. Pushes the mutated node roots back to the remote Sparks

From your Mac repo root (stream-run on Spark0, passing Spark1/2/3 SSH targets as args):

```bash
ssh $SSH_OPTS spark0@<spark0-host> "export CENTAUR_ROOT=~/centaur-smoke/v73/run/centaur_spec_impl_v73; export CENTAUR_VENV=~/centaur-smoke/v73/run/venv; sh -s -- spark1@<spark1-host> spark2@<spark2-host> spark3@<spark3-host>" < ./scripts/centaur_spark_ring_rsync_v73.sh
```

Notes:

- Use a dedicated `remote_base_dir` (4th arg) if you want the script to manage a clean namespace on each Spark (it uses `rsync --delete`).
- This is still a staging workaround; it exercises ring data flow and produces runnable node roots on Spark1/2/3, but it is not a shared-root deployment model.

## “Real ring” option B: shared filesystem for peer roots

If you can provide a shared writable filesystem path visible on Spark0/1/2/3 (NFS, CephFS, etc), set each peer root to a real shared path and run `hyor-ring-step` directly without rsync staging.
