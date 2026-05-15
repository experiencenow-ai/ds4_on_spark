# DS4 Performance Icebergs: Current Spark0 Truth

Status as of the B=64/B=128 TCP streaming handoff runs on 2026-05-15: DS4 now
has a finite three-stage handoff proof with direct binary activation transfer.
Stage0 exports HC boundary activations, stage1 imports/exports the next
boundary, and stage2 imports that boundary and emits finite final logits.

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
| Latest finite TCP streaming achieved rate | 80.887 rows/s at B=128, microbatch_count=2 |

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

The next run replaced file copy with direct TCP binary activation transfer and
ran resident stage processes with two microbatches in flight:

| Batch | Microbatches | Boundary bytes | Achieved streaming rows/s | Pipeline bound rows/s | Max transfer ms | Bubble overhead | Final logits hash |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 64 | 2 | 4,194,304 | 46.843 | 64.093 | 126.560 | 0.368 | `fnv64:668711b0b3638b46` |
| 128 | 2 | 8,388,608 | 80.887 | 133.647 | 113.545 | 0.652 | `fnv64:998c235e14177500` |

The streaming rate is computed from measured per-microbatch stage times and
actual TCP boundary transfer times. One-time process startup and model preload
remain outside the steady-state number; production still needs resident stage
services instead of one-shot SSH-launched probes. The B=256 follow-up was
stopped after a stale Spark0 `ds4` process lock blocked stage0 startup; it was
not counted as a model throughput failure.

This is still a probe path, not production generation: no scheduler, no PP=1
parity claim, and no provider eligibility. But it now proves direct binary
streaming handoff with real boundary data and finite final logits.

Do not claim >15 tok/s generation until a 43-layer B>=16 path completes with
finite output/hash using real stage boundary activations.

## Next Code Change

Turn the proof into a resident service next:

- keep each stage's owned layer tensors resident using the explicit preload path;
- replace SSH-launched one-shot stage commands with long-lived stage workers;
- add process-lock cleanup/fail-fast so stale probes cannot block B>=256;
- run PP=1 versus local PP=N parity before calling the distributed path eligible;
- keep direct binary activation transfer over the high-speed links;
- then rerun B=256/B=512 after the worker/process-lock path is stable.

Latest summary artifact:
`fixtures/perf_icebergs/spark0_perf_iceberg_summary.latest.json`.

Latest handoff artifacts:

- `fixtures/stage_handoff/local_b64_finite_logits.example.json`
- `fixtures/stage_handoff/spark012_b64_file_handoff_finite_logits.example.json`
- `fixtures/stage_handoff/spark012_b64_tcp_streaming_mb2.example.json`
- `fixtures/stage_handoff/spark012_b128_tcp_streaming_mb2.example.json`
