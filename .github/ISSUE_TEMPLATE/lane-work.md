---
name: Lane work item
about: A track-claimable unit of work with enforced acceptance evidence
title: "[track:?] short outcome description"
labels: ["status:queued"]
---

## North star

<!--
One sentence. Must be observable. "X runs and returns Y" is good. "Improve Z" is not.
-->

## Why this matters now

<!--
Connect to Centaur vision or to an upstream blocker. If you cannot explain why now, this issue is not ready to be in the backlog.
-->

## Target repo

<!--
The repo where the PR will be opened. The issue stays in ds4_on_spark; the PR can be in any of these:
- experiencenow-ai/ds4_on_spark   (Spark deployment, ds4 patches, evaluation harnesses, vLLM/SGLang benchmarks, coordination infra)
- experiencenow-ai/centaur        (state-machine factory, provider bindings, model-router, evolution domains)
- experiencenow-ai/trimind-brain  (memory codec, brain forest, IVF-PQ search, LongMemEval harness)
- experiencenow-ai/tc             (Tockchain firmware; push via ethpred/tc fork)
- antirez/ds4                     (upstream ds4 patches; push via ethpred/ds4 fork)
Replace this comment with the chosen repo path.
-->
experiencenow-ai/ds4_on_spark
## Hardware required

<!--
Choose one hw label and put it here. The label on the issue must match.
- hw:none           pure code work
- hw:any-1          one Spark, any
- hw:any-3          three Sparks, any group
- hw:spark-2-3-4    specific layout
- hw:spark-3-4-5    specific layout
- hw:spark-6        isolated
-->

## Scope

**Write:**
<!-- paths -->

**Read-only (context):**
<!-- paths -->

## Acceptance gates

All gates must produce raw program output in the merged PR body, not summaries.

1. <!-- Gate 1 with the exact command and the expected observable output shape -->
2. <!-- Gate 2 -->
3. <!-- Gate 3 -->

## Forbidden patterns

<!--
Specific anti-patterns for this work item. Examples:
- Synthetic input instead of real tokens
- Skipping the hardware run and committing only the harness
- Adding new JSON schemas instead of executing
-->

## Dependencies

**Depends on:** <!-- #N (must be closed first) -->
**Blocks:** <!-- #N (cannot proceed without this) -->

## Track affinity hint

<!--
Which track's accumulated context fits best? This is a hint, not a binding.
Any track may claim if hardware is compatible and dependencies clear.
-->
