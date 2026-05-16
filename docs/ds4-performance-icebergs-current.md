# DS4 Performance Icebergs: Current Truth

Status as of the 2026-05-15 base-pipeline ceiling window:
DS4 has finite three-stage TCP binary handoff with real boundary activations.
Each stage preloads its owned layer range, stage2 includes the output head, and
successful runs emit finite logits hashes. This is still not production
generation: PP=1 parity is not run and `production_generation_eligible=false`.

## Current Best

| Metric | Value |
| --- | ---: |
| Best achieved streaming rows/s | 210.999 at B=512, microbatches=16 |
| Best corrected steady-state bound | 244.270 rows/s at B=1024, microbatches=4 |
| Best B=512 corrected steady-state bound | 237.492 rows/s |
| Exceeds 15 rows/s | true |
| Exceeds 250 rows/s | false |
| PP=1 parity | not run |
| Current primary bottleneck | stage compute, not transfer or pipeline bubble |

## B/Depth Probe

The legacy `pipeline_rows_per_s_bound` field is preserved for compatibility.
The corrected utilization number is `steady_state_pipeline_bound_rows_per_s`,
which treats stage compute and TCP transfers as separate overlapped resources.

| Batch | Microbatches | Achieved rows/s | Legacy bound | Corrected steady bound | Bubble | Slowest stage | Stage balance | Max transfer ms | Final logits hash | Status |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| 512 | 8 | 188.506 | 189.717 | 237.966 | 0.006 | stage0, 2,151.565 ms | 1.124 | 64.023 | `fnv64:5c9c39e9a1665737` | finite |
| 512 | 16 | 209.036 | 191.615 | 237.492 | 0.000 | stage0, 2,155.858 ms | 1.100 | 241.836 | `fnv64:5c9c39e9a1665737` | finite, current best |
| 1024 | 4 | 156.443 | 198.484 | 244.270 | 0.269 | stage0, 4,192.088 ms | 1.084 | 120.796 | `fnv64:c5078c09143550f8` | finite, does not improve |

B=1024 did not hit a memory or residency failure, but it did not improve over
B=512/mb16. The achieved result is fill/drain limited at mb4, while the
steady-state ceiling remains compute-bound around 244 rows/s.

## Split Rebalance

The original split remains the best measured split:
`[0,15), [15,29), [29,43)+head`.

| Split | Batch/mb | Achieved rows/s | Corrected steady bound | Bubble | Slowest stage | Stage balance | Hash | Read |
| --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- |
| `[0,15),[15,29),[29,43)+head` | 512/16 | 209.036 | 237.492 | 0.000 | stage0, 2,155.858 ms | 1.100 | `fnv64:5c9c39e9a1665737` | best achieved |
| `[0,14),[14,28),[28,43)+head` | 512/8 | 183.614 | 242.309 | 0.061 | stage2, 2,113.002 ms | 1.076 | `fnv64:5c9c39e9a1665737` | stage2/head side too heavy |
| `[0,14),[14,29),[29,43)+head` | 512/8 | 186.146 | 243.480 | 0.015 | stage1, 2,102.841 ms | 1.065 | `fnv64:5c9c39e9a1665737` | stage1 becomes bottleneck |
| `[0,16),[16,30),[30,43)+head` | 512/8 | 180.991 | 223.501 | 0.026 | stage0, 2,290.820 ms | 1.240 | `fnv64:5c9c39e9a1665737` | stage0 too heavy |

## Output Head

Stage2 includes the output head, but a narrow head-only check does not show it
as the current bottleneck:

| Batch | Best head ms | Heads/s | Finite logits | Hash |
| ---: | ---: | ---: | --- | --- |
| 512 | 2.527 | 395.732 | yes | `d99730a7a09d8f8a` |
| 1024 | 2.533 | 394.835 | yes | `d99730a7a09d8f8a` |

This is consistent with the earlier roughly 380-395 heads/s result. Stage2
full-stage time is around 1.96-1.98 s at B=512, so the head-only probe is not
the visible stage2 bottleneck.

## Kernel Profile

Per-layer profiling on the default split shows the stage-compute bottleneck is
routed MoE, not attention, transfer, output head, or residency fallback.

| Stage | Layers | Sum layer ms | Sum FFN ms | Sum routed MoE ms | FFN share | MoE share |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| stage0 | `[0,15)` | 2,066.737 | 1,945.872 | 1,910.568 | 94.15% | 92.44% |
| stage1 | `[15,29)` | 1,892.529 | 1,775.551 | 1,739.909 | 93.82% | 91.94% |
| stage2 | `[29,43)+head` | 1,887.297 | 1,772.436 | 1,736.867 | 93.91% | 92.03% |

The slowest stage remains stage0. Its worst profiled layer was layer 2 at
146.076 ms, with 137.422 ms in FFN and 134.959 ms in routed MoE.

## Optimization Attempt

One bounded runtime-kernel variant was tested in the full B=512/mb16 streaming
path: `DS4_CUDA_MOE_TILE4=1`.

| Run | Achieved rows/s | Corrected steady bound | Slowest stage | Slowest service ms | Hash | Read |
| --- | ---: | ---: | --- | ---: | --- | --- |
| Default | 209.036 | 237.492 | stage0 | 2,155.858 | `fnv64:5c9c39e9a1665737` | baseline |
| TILE4 | 209.950 | 237.812 | stage0 | 2,152.962 | `fnv64:5c9c39e9a1665737` | +0.44% achieved |

The TILE4 variant is a tiny safe improvement, not a new ceiling. A narrow MoE
variant sweep on stage0 layers 0, 3, and 14 showed `DS4_CUDA_MOE_NO_P2=1` is
much slower, so the sorted P2 path is required. `DS4_CUDA_MOE_DOWN_BLOCK16=1`
was neutral to worse.

## P2 Inner Timing

`DS4_CUDA_MOE_P2_INNER_PROFILE=1` splits routed MoE into queue build, pointer
table setup, gate/up, quantize, down, and accumulation. Stage0 B=512/mb16 shows
gate/up dominates.

| Layer | Queue ms | Pointer ms | Gate/up ms | Quantize ms | Down ms | Accum ms | Total ms | Bottleneck |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 0.020 | 0.034 | 116.993 | 0.250 | 16.798 | 0.321 | 134.415 | gate/up |
| 1 | 0.020 | 0.038 | 117.214 | 0.250 | 16.725 | 0.321 | 134.567 | gate/up |
| 2 | 0.020 | 0.034 | 117.682 | 0.250 | 16.770 | 0.316 | 135.073 | gate/up |
| 3 | 0.020 | 0.013 | 110.051 | 0.261 | 14.538 | 0.330 | 125.212 | gate/up |
| 14 | 0.023 | 0.020 | 110.734 | 0.266 | 14.586 | 0.333 | 125.962 | gate/up |

The first bounded P2 code change stops writing P2 `gate_out` and `up_out`
unless `DS4_CUDA_MOE_WRITE_GATE_UP=1`, matching the tiled kernels' existing
aux-write behavior. The component profile barely moves, but the full pipeline
does improve.

| Run | Achieved rows/s | Corrected steady bound | Slowest stage | Slowest service ms | Hash | Read |
| --- | ---: | ---: | --- | ---: | --- | --- |
| Default | 209.036 | 237.492 | stage0 | 2,155.858 | `fnv64:5c9c39e9a1665737` | baseline |
| TILE4 | 209.950 | 237.812 | stage0 | 2,152.962 | `fnv64:5c9c39e9a1665737` | tiny env-only gain |
| P2 skip aux writes | 210.999 | 237.992 | stage0 | 2,151.329 | `fnv64:5c9c39e9a1665737` | current best |

## Current Blocker

The base pipeline still did not reach 250 rows/s. Pipeline bubble is
effectively gone at B=512/mb16 and transfer is not material. The current
bottleneck is stage0 P2 routed MoE gate/up compute, with layer 2 gate/up at
roughly 117.7 ms of 135.1 ms total routed MoE.

Exact next code change: optimize the P2 gate/up dot kernel itself, or replace
the P2 gate/up path with a correctly slice-aware expert-tile gate/up kernel.
Queue build, pointer-table setup, down, and accumulation are not the primary
limit.

Latest handoff artifacts:

- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_tile4.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_skipaux.example.json`
- `fixtures/stage_handoff/spark012_b1024_tcp_resident_mb4.example.json`
- `fixtures/stage_handoff/spark012_split_014_028_043_b512_mb8.example.json`
- `fixtures/stage_handoff/spark012_split_014_029_043_b512_mb8.example.json`
- `fixtures/stage_handoff/spark012_split_016_030_043_b512_mb8.example.json`

Latest kernel-profile artifacts:

- `fixtures/stage_kernel_profile/spark0_stage0_kernel_profile_b512.example.json`
- `fixtures/stage_kernel_profile/spark1_stage1_kernel_profile_b512.example.json`
- `fixtures/stage_kernel_profile/spark2_stage2_kernel_profile_b512.example.json`
- `fixtures/stage_kernel_profile/spark0_moe_variant_sweep_b512.example.json`
- `fixtures/moe_p2_inner_profile/spark0_p2_inner_b512_mb16_before.example.json`
- `fixtures/moe_p2_inner_profile/spark0_p2_inner_b512_mb16_skipaux.example.json`
