# DS4 Performance Icebergs: Current Truth

Status as of the 2026-05-15 streaming-stage utilization window:
DS4 has finite three-stage TCP binary handoff with real boundary activations.
Each stage preloads its owned layer range, stage2 includes the output head, and
successful runs emit finite logits hashes. This is still not production
generation: PP=1 parity is not run and `production_generation_eligible=false`.

## Current Best

| Metric | Value |
| --- | ---: |
| Best achieved streaming rows/s | 188.506 at B=512, microbatches=8 |
| Best corrected steady-state bound | 243.610 rows/s at B=1024, microbatches=2 |
| Best B=512 corrected steady-state bound | 237.966 rows/s |
| Exceeds 15 rows/s | true |
| PP=1 parity | not run |
| Current primary bottleneck | stage0 compute, not transfer |

## Utilization Sweep

The legacy `pipeline_rows_per_s_bound` field is preserved for compatibility.
The corrected utilization number is `steady_state_pipeline_bound_rows_per_s`,
which treats stage compute and TCP transfers as separate overlapped resources.

| Batch | Microbatches | Achieved rows/s | Legacy bound | Corrected steady bound | Bubble | Fill ms | Drain ms | Max transfer ms | Slowest resource | Final logits hash | Status |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| 256 | 8 | 179.361 | 169.816 | 229.220 | 0.000 | 4,236.172 | 1,025.349 | 54.928 | stage0 compute, 1,116.833 ms | `fnv64:66c3ff107ae15075` | finite |
| 512 | 4 | 153.374 | 193.844 | 238.018 | 0.264 | 7,459.326 | 1,966.513 | 72.530 | stage0 compute, 2,151.101 ms | `fnv64:5c9c39e9a1665737` | finite |
| 512 | 8 | 188.506 | 189.717 | 237.966 | 0.006 | 7,397.494 | 2,142.330 | 64.023 | stage0 compute, 2,151.565 ms | `fnv64:5c9c39e9a1665737` | finite |
| 1024 | 2 | 112.007 | 201.665 | 243.610 | 0.800 | 14,413.096 | 3,871.460 | 108.211 | stage0 compute, 4,203.435 ms | `fnv64:c5078c09143550f8` | finite, too shallow |
| 1024 | 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | blocked | none | blocked by live Spark0 ds4 process |

## Bubble Breakdown

| Run | Stage compute ms | Boundary send/recv ms | Worker idle wait ms | Read |
| --- | ---: | ---: | ---: | --- |
| B=256 mb=8 | 26,271.719 | 431.792 | 4,809.525 | stage0 is slowest; transfer is small |
| B=512 mb=4 | 25,618.429 | 367.474 | 7,870.014 | too few microbatches |
| B=512 mb=8 | 49,946.539 | 626.158 | 9,220.731 | best achieved; still stage0-bound |
| B=1024 mb=2 | 26,241.567 | 282.709 | 14,790.250 | fill/drain dominates |

## Stale Lock Behavior

The runner now handles two lock cases:

- dead-PID `/tmp/ds4.lock` files are renamed to `.stale.*`;
- safe stale `--cuda-batch-stack-probe` processes are terminated before the run.

The B=1024/mb4 attempt correctly refused to kill an unrelated live Spark0
generation process:

```text
./ds4 --cuda ... -p Explain Redis streams in one paragraph ...
```

## Next Code Change

Turn the probe into a real resident service with persistent stage workers and a
small control protocol. The next utilization target is B=1024 with depth >= 4
after Spark0 is idle; the next correctness target remains the DS4 split-forward
hook for PP=1 versus local PP=N parity.

Latest handoff artifacts:

- `fixtures/stage_handoff/spark012_b256_tcp_resident_mb8.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb4.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb8.example.json`
- `fixtures/stage_handoff/spark012_b1024_tcp_resident_mb2.example.json`
- `fixtures/stage_handoff/spark012_b1024_tcp_resident_mb4_blocked.example.json`
