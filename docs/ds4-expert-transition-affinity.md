# DS4 Expert Transition Affinity

The next routing question is whether expert choices are clumpy across adjacent
layers. If `P(next expert | current expert)` is concentrated, we can reduce
cross-Spark transits by making expert ownership layer-specific:

```text
spark = expert_owner_table[layer][expert_id]
```

That keeps runtime code simple. The complexity lives in an offline table built
from route dumps.

## Analyzer

Run against DS4 `ffn_moe_topk-<layer>_pos<pos>.i32` dumps:

```bash
python3 scripts/analyze_ds4_expert_transitions.py \
  --dump-dir /tmp/ds4_expert_fuzz_20260512T1335Z \
  --pos 0 --topk 6 --experts 256 --logical-lanes 32 --sparks 8 \
  --json-out /tmp/ds4_expert_fuzz_20260512T1335Z/expert_transition_affinity.json
```

Or include it in the standard top-k dump bundle:

```bash
python3 scripts/ds4_topk_dump_recommendations.py \
  --dump-dir /tmp/ds4_expert_fuzz_20260512T1335Z \
  --bundle-dir /tmp/ds4_expert_fuzz_20260512T1335Z/scheduler_bundle_pos0 \
  --pos 0 --topk 6 \
  --probe-expert-queueing --probe-expert-transitions \
  --probe-experts 256 --probe-transition-sparks 8 --probe-transition-logical-lanes 32
```

## Metrics

The probe counts every adjacent-layer selected-expert pair. With `topk=6`, each
token contributes `36` transition pairs per layer pair.

It reports:

- `weighted_top1_mass`: for a current expert, the probability mass on its most
  likely next expert, weighted by how often that current expert appears.
- `weighted_top4_mass`, `weighted_top8_mass`, etc.: how much next-expert mass
  is captured by the top-N conditional choices.
- `weighted_normalized_entropy`: `0` means deterministic next expert; `1`
  means nearly uniform over all experts.
- `mod_lane_same_spark_rate`: transition-pair stay-local rate under
  `expert_id % logical_lanes`.
- `affinity_same_spark_rate`: stay-local rate under a balanced greedy
  layer-specific table.
- `affinity_cross_spark_reduction`: how much cross-Spark traffic the affinity
  table removes versus the mod-lane baseline.

## Greedy Table

The table builder starts layer 0 with the current mod-lane map. For each next
layer, it assigns every next-layer expert to the Spark that contributed the
largest inbound transition mass from the previous layer, while keeping per-Spark
expert counts balanced.

This is intentionally not the final optimizer. It is a low-risk first bound:
if the greedy table barely improves same-Spark rate, the route signal is weak.
If it improves materially, a stronger graph partitioner is worth building.
