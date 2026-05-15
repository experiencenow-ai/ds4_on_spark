# DS4 Performance Icebergs: Current Spark0 Truth

Status as of the B=128/B=256/B=512 resident-stage handoff runs on 2026-05-15:
DS4 now has finite three-stage streaming handoff with direct binary activation
transfer. Each stage process preloads its owned layer range once, processes
multiple microbatches, and stage2 emits finite final logits.

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
| Latest finite TCP streaming achieved rate | 188.511 rows/s at B=512, microbatch_count=8 |

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

The next runs replaced file copy with direct TCP binary activation transfer and
ran resident stage processes with multiple microbatches in flight:

| Batch | Microbatches | Boundary bytes | Achieved rows/s | Pipeline bound rows/s | Bubble overhead | Max transfer ms | Final logits hash |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 64 | 2 | 4,194,304 | 46.843 | 64.093 | 0.368 | 126.560 | `fnv64:668711b0b3638b46` |
| 128 | 2 | 8,388,608 | 80.887 | 133.647 | 0.652 | 113.545 | `fnv64:998c235e14177500` |
| 128 | 4 | 8,388,608 | 117.402 | 133.377 | 0.136 | 325.445 | `fnv64:998c235e14177500` |
| 256 | 2 | 16,777,216 | 96.816 | 169.520 | 0.751 | 23.825 | `fnv64:66c3ff107ae15075` |
| 256 | 4 | 16,777,216 | 140.637 | 175.008 | 0.244 | 44.962 | `fnv64:66c3ff107ae15075` |
| 512 | 2 | 33,554,432 | 108.136 | 187.241 | 0.732 | 49.490 | `fnv64:5c9c39e9a1665737` |
| 512 | 4 | 33,554,432 | 152.777 | 190.017 | 0.244 | 67.827 | `fnv64:5c9c39e9a1665737` |
| 512 | 8 | 33,554,432 | 188.511 | 188.987 | 0.003 | 81.893 | `fnv64:5c9c39e9a1665737` |

The streaming rate is computed from measured per-microbatch stage times and
actual TCP boundary transfer times. One-time process startup and model preload
remain outside the steady-state number. The B=256/microbatch_count=4 run also
proved stale-lock cleanup: preflight found and terminated a stale Spark2
`--cuda-batch-stack-probe` process before starting the new run.

This is still a probe path, not production generation: no scheduler, no PP=1
parity claim, and no provider eligibility. But it now proves direct binary
streaming handoff with real boundary data and finite final logits.

The B=256/microbatch_count=4 run exposed and fixed a handoff race: the sender
must wait for the exact boundary byte count before reading a newly-created
boundary file. Without that check it can send a zero-byte file while the stage
is still writing.

## Overhead Split

| Run | Stage compute ms | Boundary send/recv ms | Worker idle wait ms | Dominant gap |
| --- | ---: | ---: | ---: | --- |
| B=128 mb=4 | 7,743.025 | 773.556 | 2,822.435 | fill/drain idle plus Spark1->Spark2 send outliers |
| B=256 mb=4 | 13,581.121 | 248.537 | 4,297.231 | fill/drain idle |
| B=512 mb=2 | 13,495.351 | 154.556 | 7,869.990 | too few microbatches |
| B=512 mb=8 | 49,899.559 | 675.559 | 9,293.794 | essentially saturated; bubble overhead 0.003 |

PP=1 parity remains not run. The current parity probe still reports the exact
blocker: the repo validation path lacks `torch`/`transformers`, and the DS4
runtime still lacks a repo-owned split-forward hook for PP=1 versus PP=N model
comparison. Do not mark the distributed provider eligible until that hook exists
and parity passes.

## Next Code Change

Turn the proof into a real resident service next:

- keep each stage's owned layer tensors resident using the explicit preload path;
- replace SSH-launched one-shot probes with long-lived worker daemons and a small control protocol;
- keep exact-size boundary readiness before every send;
- implement the DS4 split-forward hook needed for PP=1 versus local PP=N parity;
- keep direct binary activation transfer over the high-speed links;
- after daemonization, rerun B=512/B1024 with enough microbatches to stay saturated.

## MTP PR Triage

- PR #1084 supersedes #1082 for the antirez CUDA cache-sync acceptance lane:
  it has accept_est 1.0 and target_next_mismatch_events=0, but generation is
  still only 1.38 t/s versus 15.07 t/s baseline. Park/rebase later; do not
  merge into the performance pipeline path yet.
- PR #1082 is superseded by #1084 and should be closed after any unique parser
  bits are cherry-picked, if still needed.
- PR #1067 remains parked for the llama.cpp one-token MTP correctness oracle.
  Keep only if that oracle is still needed; otherwise close as deferred.

Latest summary artifact:
`fixtures/perf_icebergs/spark0_perf_iceberg_summary.latest.json`.

Latest handoff artifacts:

- `fixtures/stage_handoff/local_b64_finite_logits.example.json`
- `fixtures/stage_handoff/spark012_b64_file_handoff_finite_logits.example.json`
- `fixtures/stage_handoff/spark012_b64_tcp_streaming_mb2.example.json`
- `fixtures/stage_handoff/spark012_b128_tcp_streaming_mb2.example.json`
- `fixtures/stage_handoff/spark012_b128_tcp_resident_mb4.example.json`
- `fixtures/stage_handoff/spark012_b256_tcp_resident_mb2.example.json`
- `fixtures/stage_handoff/spark012_b256_tcp_resident_mb4.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb2.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb4.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb8.example.json`
