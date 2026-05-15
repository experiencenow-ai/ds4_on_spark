# DS4 Performance Icebergs: Current Spark0 Truth

Status as of the B=64 stage-handoff run on 2026-05-15: DS4 now has a finite
three-stage handoff proof. Stage0 exports a host-visible HC boundary file,
stage1 imports and exports the next boundary, and stage2 imports that boundary
and emits finite final logits.

## Latest Spark0 Result

| Metric | Value |
| --- | ---: |
| Best finite-output handoff rows/s, sequential | 29.666 |
| Exceeds 15 rows/s | true |
| Realization vs 409 tok/s ceiling | not proven |
| Realization vs 558 tok/s ceiling | not proven |
| Realization vs 620 tok/s ceiling | not proven |
| Output-head-only cap | 381.873 heads/s trusted warm result |
| Previous blocker | generic demand-cache upload inside stage preload |
| Latest finite handoff pipeline bound | 84.062 rows/s at B=64 |

The output head produced finite logits:

```text
best_ms=2.619
best_heads_per_s=381.873
logits_fnv64=1357e489ff9c56fd
```

The older full-stack probes failed before any throughput claim:

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

The 409/558/620 tok/s numbers remain component ceilings, not achieved generation
throughput. The useful correction is that the first residency iceberg was
fixable: stage preload was not explicit enough. With explicit preload plus
boundary file import/export, the B=64 local sequential handoff now completes:

```text
Spark0-local [0,15): 761.339 ms
Spark0-local [15,29): 678.049 ms
Spark0-local [29,43)+head: 717.930 ms
Final logits hash: fnv64:668711b0b3638b46
Sequential rows/s: 29.666
Pipeline bound: 84.062 rows/s
```

The same B=64 boundary files were handed Spark0 -> Spark1 -> Spark2 using scp
through the Mac coordinator for this correctness proof:

```text
Spark0 [0,15): 761.339 ms
Spark1 [15,29): 716.549 ms
Spark2 [29,43)+head: 677.842 ms
Final logits hash: fnv64:668711b0b3638b46
Pipeline bound: 84.062 rows/s
```

This is still a probe path, not production generation: no scheduler, no
streaming transport, no PP=1 parity claim, and file handoff time was not
separately optimized. But it is no longer stage-compute-only. Real boundary data
flows between stages and produces finite final logits.

Do not claim >15 tok/s generation until a 43-layer B>=16 path completes with
finite output/hash using real stage boundary activations.

## Next Code Change

Wire the real streaming layer pipeline next:

- keep each stage's owned layer tensors resident using the explicit preload path;
- run PP=1 versus local PP=N parity before calling the distributed path eligible;
- replace scp/file handoff with direct binary transfer over the 100G links;
- keep the same final logits hash through Spark0 -> Spark1 -> Spark2;
- then measure B=64/B=128 with transfer time separated from stage compute.

Latest summary artifact:
`fixtures/perf_icebergs/spark0_perf_iceberg_summary.latest.json`.

Latest handoff artifacts:

- `fixtures/stage_handoff/local_b64_finite_logits.example.json`
- `fixtures/stage_handoff/spark012_b64_file_handoff_finite_logits.example.json`
