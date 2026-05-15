# DS4 Performance Icebergs: Current Spark0 Truth

Status as of `ds4-perf-iceberg-20260515T080056Z` plus the later explicit
stage-preload live run: full-stack DS4 generation still does not exceed 15 tok/s
because an end-to-end 43-layer request path has not completed with real boundary
handoff. The previous Spark0 iceberg was identified more precisely: the stage
preload helper was still using the generic demand-cache range uploader, so the
failure looked like a lazy MoE upload even though the runner intended preload.

## Latest Spark0 Result

| Metric | Value |
| --- | ---: |
| Best full-stack tok/s | not proven |
| Exceeds 15 tok/s | false |
| Realization vs 409 tok/s ceiling | not proven |
| Realization vs 558 tok/s ceiling | not proven |
| Realization vs 620 tok/s ceiling | not proven |
| Output-head-only cap | 393.267 heads/s |
| Previous blocker | generic demand-cache upload inside stage preload |
| Latest three-way stage bound | 79.963 rows/s at B=64 |

The output head produced finite logits:

```text
best_ms=2.543
best_heads_per_s=393.267
logits_fnv64=d99730a7a09d8f8a
```

The earlier full-stack probes failed before any throughput claim:

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
generation throughput. The useful correction is that the first residency iceberg
was fixable: stage preload was not explicit enough. The live patched runtime now
preloads owned-stage tensors through `ds4_gpu_preload_model_range(...)` and ran
all three Sparks successfully:

```text
Spark0 [0,15): 800.373 ms for B=64, 79.963 rows/s
Spark1 [15,29): 656.242 ms for B=64, 97.525 rows/s
Spark2 [29,43)+head: 724.466 ms for B=64, 88.341 rows/s
Pipeline bound: 79.963 rows/s
```

This proves stage-local owned expert residency and layer execution can run
across all three Sparks. It still does not prove end-to-end generation because
stage inputs are synthetic and no activation payload is handed from Spark0 to
Spark1 to Spark2 yet.

Do not claim >15 tok/s generation until a 43-layer B>=16 path completes with
finite output/hash using real stage boundary activations.

## Next Code Change

Wire the real layer pipeline next:

- pass the `[batch, sequence, hc_mult, hidden_size]` boundary tensor from stage
  0 to stage 1, then stage 1 to stage 2;
- keep each stage's owned layer tensors resident using the explicit preload path;
- run PP=1 versus local PP=N parity before calling the distributed path eligible;
- then run the same B=64/B=128 stage split with real activation transfer and
  output/hash accounting.

Latest summary artifact:
`fixtures/perf_icebergs/spark0_perf_iceberg_summary.latest.json`.
