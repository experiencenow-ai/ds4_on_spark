# Centaur HyoR ring rehearsal: Spark1/Spark2/Spark3 (filesystem sim)

Goal: prepare repeatable Spark1/Spark2/Spark3 ring steps **without needing extra hardware yet**.

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

