# Centaur Diamond Loop

This is the production operator loop for Centaur diamond refinement on the Spark
ring. It runs Centaur target discovery and DGX batching on one free Spark, pulls
verified candidates back to a central human review queue, and releases the lazy
vLLM backend when the run ends.

The loop does not approve, apply, or open PRs. Human review remains the gate.

## Daily Run

Default production shape:

```sh
./scripts/centaur_diamond_loop.sh
```

Important defaults:

- Sparks are tried in order: `spark6 spark7 spark0 spark3`.
- The lazy proxy endpoint is `http://127.0.0.1:8000`.
- The model is `deepseek-ai/DeepSeek-V4-Flash`.
- Each run prepares `20` targets times `16` prompt variants, for `320` prompts.
- The remote Centaur checkout is `~/centaur`.
- The queue root is `~/centaur_review_queue`.

Dry-run the local plan without SSH:

```sh
./scripts/centaur_diamond_loop.sh --dry-run --run-id smoke
```

Override a run:

```sh
MODEL=Qwen/Qwen3-Coder-Next-32B-Instruct \
WORKERS=128 \
./scripts/centaur_diamond_loop.sh \
  --sparks "spark7 spark6 spark0 spark3" \
  --target-count 20 \
  --prompt-variants 16
```

The remote execution path is:

```sh
python3 -m v2.centaur_over_shinka_cli discover-targets ...
python3 -m v2.centaur_over_shinka_cli prepare-dgx-run --targets ... --accept-large-run ...
CENTAUR_VERIFY_AFTER_DGX=1 ./run_dgx_sparkrunner.sh
```

## Backpressure

Before selecting a Spark, the driver checks:

```sh
ssh spark6 'curl -fsS http://127.0.0.1:8000/ds4/status'
```

A Spark is eligible only when the lazy proxy reports no active backend and no
current model. Busy Sparks are skipped. If the backend PID has existed for more
than four hours, the Spark is abandoned for this cycle and the reason is logged
under `failures/`.

After every attempted run, successful or failed, the driver calls:

```sh
ssh spark6 'PORT=8000 ~/bin/ds4_vllm_lazy_release.sh'
```

The remote run also checks free disk before discovery and exits before model
load when the run directory has less than `MIN_FREE_GIB` available.

## Review Queue

Verified candidates are materialized by:

```sh
./scripts/centaur_release_review_queue.sh \
  --verified-dir /tmp/run/dgx_batch/verified \
  --queue-root ~/centaur_review_queue \
  --run-id centaur_diamond_20260524T000000Z \
  --spark spark6 \
  --model deepseek-ai/DeepSeek-V4-Flash
```

Queue layout:

```text
~/centaur_review_queue/
  pending/<target_id>/<run_date>/<candidate_id>/
    original.py
    candidate.py
    diff.patch
    verification.json
    target.json
    proposal.json
    metadata.json
    review_packet.md
  approved/
  rejected/
  incoming/<run_id>/
  runs/<run_id>/
  failures/<timestamp>-<stage>-<spark>.log
  stats.json
```

Accepted targets are skipped for the next seven days while they remain under
`pending/` or `approved/`, so the nightly loop keeps moving across the codebase.

## Applying Approved Candidates

After a human reviews a pending entry, move the whole candidate directory under
`approved/`, then apply exactly that candidate:

```sh
./scripts/apply_approved.sh \
  ~/centaur_review_queue/approved/<target_id>/<run_date>/<candidate_id> \
  --centaur-repo ~/centaur
```

The apply script:

- verifies the entry is under `approved/`
- replaces exactly one copy of `original.py` with `candidate.py`
- creates a branch named `centaur-approved/<timestamp>-<candidate>`
- commits the changed target file
- never creates a PR

Preview without editing:

```sh
./scripts/apply_approved.sh <candidate_dir> --centaur-repo ~/centaur --dry-run
```

## Observability

`stats.json` keeps a rolling 30-day window. It records raw runs and aggregates:

- `per_target`: proposals, accepted, acceptance rate, mean diamond score
- `per_model`: proposals, accepted, acceptance rate, mean diamond score
- `per_day`: candidates produced, accepted, wall-clock hours, diamond score sum
- `per_spark`: total wall-clock hours and model-load count
- `best_models`: top models by `acceptance_rate * diamond_score_sum`

Weekly reporting can be either mail or committed docs. A simple docs snapshot:

```sh
mkdir -p docs/diamond-loop-stats
cp ~/centaur_review_queue/stats.json docs/diamond-loop-stats/stats-$(date -u +%Y%m%d).json
```

## Failure Handling

The loop continues to the next Spark when it hits:

- Spark unreachable
- lazy proxy timeout
- model held for more than four hours
- full disk on the remote run directory
- model load failure
- runner subprocess crash
- verifier failure
- rsync failure

Each failure writes a timestamped log under:

```text
~/centaur_review_queue/failures/
```

Those logs include the run id, Spark, model, stage, and captured command output
where available.

## Schedule

Cron example for a nightly run plus a weekly stats snapshot:

```cron
15 2 * * * cd ~/ds4_on_spark && ./scripts/centaur_diamond_loop.sh >> ~/centaur_review_queue/loop.log 2>&1
45 8 * * 1 cd ~/ds4_on_spark && mkdir -p docs/diamond-loop-stats && cp ~/centaur_review_queue/stats.json docs/diamond-loop-stats/stats-$(date -u +\%Y\%m\%d).json
```

The acceptance run is operational, not just unit-test based: let the nightly
loop run for at least 24 hours, accumulate five days of non-zero acceptance in
`stats.json`, then apply at least one human-approved candidate with
`apply_approved.sh`.
