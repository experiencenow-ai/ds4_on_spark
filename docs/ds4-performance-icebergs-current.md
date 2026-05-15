# DS4 Performance Icebergs: Current Spark0 Truth

Status as of `ds4-perf-iceberg-20260515T080056Z`: full-stack DS4 still does
not exceed 15 tok/s on Spark0. The probe did not complete any 43-layer
decode/batch path with finite output.

## Latest Spark0 Result

| Metric | Value |
| --- | ---: |
| Best full-stack tok/s | not proven |
| Exceeds 15 tok/s | false |
| Realization vs 409 tok/s ceiling | not proven |
| Realization vs 558 tok/s ceiling | not proven |
| Realization vs 620 tok/s ceiling | not proven |
| Output-head-only cap | 393.267 heads/s |
| Primary blocker | lazy_moe_range_upload |

The output head produced finite logits:

```text
best_ms=2.543
best_heads_per_s=393.267
logits_fnv64=d99730a7a09d8f8a
```

The full-stack probes failed before any throughput claim:

```text
CUDA model range upload sync failed for stack_stage_l4_t31_c3
CUDA model range alloc failed for stack_stage_l4_t31_c3 (64.00 MiB)
```

The B=16 batch-with-head case failed similarly:

```text
CUDA model range upload sync failed for stack_stage_l2_t29_c3
CUDA model range alloc failed for stack_stage_l2_t29_c3 (64.00 MiB)
```

## Interpretation

The 409/558/620 tok/s numbers remain component ceilings, not achieved DS4
generation throughput. The current iceberg is still CUDA weight residency:
full-stack execution reaches lazy model-range upload/allocation paths for
`stack_stage_l*_t*_c*` tensors and times out.

Do not build more orchestration around the >15 tok/s target until a 43-layer
B>=16 probe completes with finite output/hash.

## Next Code Change

Fix CUDA residency first. The runtime needs one of these before scheduler or
pipeline work can matter:

- preload exact tested layer ranges without hitting lazy range uploads;
- fail fast before a launch timeout poisons the CUDA context;
- trace `stack_stage_l*_t*_c*` to the exact tensor class and owning preload path;
- remove uncached fallback slabs from the full-stack probe path.

Latest summary artifact:
`fixtures/perf_icebergs/spark0_perf_iceberg_summary.latest.json`.
