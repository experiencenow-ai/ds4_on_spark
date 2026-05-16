# DS4 Performance Icebergs: Current Truth

Status as of the 2026-05-15 base-pipeline ceiling window:
DS4 has finite three-stage TCP binary handoff with real boundary activations.
Each stage preloads its owned layer range, stage2 includes the output head, and
successful runs emit finite logits hashes. The slice-tile8 PP=N final logits now
match a Spark0 PP=1 full-stack probe for the same model/input identity. The
batch-stack probe can now emit top-1 committed token ids for all 512 rows in
batch-head mode, but this is still not production generation: shared-prefix and
suffix prefill plus the multi-step decode/KV loop are not wired into the staged
benchmark yet, so `production_generation_eligible=false`.

## Current Best

| Metric | Value |
| --- | ---: |
| Best achieved streaming rows/s | 631.672 at B=512, microbatches=16 with slice-tile8 gate/up |
| Best B=512 committed-token decode-only output tok/s | 260.973 at B=512, microbatches=16 with batch-head token commit |
| Best corrected steady-state bound | 741.444 rows/s at B=512, microbatches=16 with slice-tile8 gate/up |
| Best B=512 corrected steady-state bound | 741.444 rows/s |
| Exceeds 15 rows/s | true |
| Exceeds 250 rows/s | true |
| PP=1 parity | passed on logits for B=512 slice-tile8 |
| Current primary bottleneck | stage compute, not transfer or pipeline bubble |

## B/Depth Probe

The legacy `pipeline_rows_per_s_bound` field is preserved for compatibility.
The corrected utilization number is `steady_state_pipeline_bound_rows_per_s`,
which treats stage compute and TCP transfers as separate overlapped resources.

| Batch | Microbatches | Achieved rows/s | Legacy bound | Corrected steady bound | Bubble | Slowest stage | Stage balance | Max transfer ms | Final logits hash | Status |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |
| 512 | 8 | 188.506 | 189.717 | 237.966 | 0.006 | stage0, 2,151.565 ms | 1.124 | 64.023 | `fnv64:5c9c39e9a1665737` | finite |
| 512 | 16 | 209.036 | 191.615 | 237.492 | 0.000 | stage0, 2,155.858 ms | 1.100 | 241.836 | `fnv64:5c9c39e9a1665737` | finite, old baseline |
| 512 | 16 | 631.672 | 452.208 | 741.444 | 0.000 | stage0, 690.545 ms | 1.108 | 354.814 | `fnv64:5c9c39e9a1665737` | finite, slice-tile8 gate/up |
| 512 | 16 | 559.396 | 427.999 | 659.235 | 0.000 | stage0, 776.658 ms | 1.123 | 354.814 | `fnv64:5c9c39e9a1665737` | finite, slice-down-tile8 rejected |
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
| P2 skip aux writes | 210.999 | 237.992 | stage0 | 2,151.329 | `fnv64:5c9c39e9a1665737` | previous best |

## Slice-Tile8 Gate/Up

The P2 inner profile showed the expert queue itself is not the bottleneck:
layer 2 queue build was 0.020 ms and pointer/descriptor setup was 0.034 ms,
while gate/up was 117.682 ms. The next bounded patch therefore adds a
slice-aware tile8 gate/up path, enabled with `DS4_CUDA_MOE_SLICE_TILE8=1`, so
batched expert slices can reuse one expert row across up to eight queued pairs.
Down projection remains on the existing P2 slices path.

| Layer | Queue ms | Pointer ms | Gate/up ms | Quantize ms | Down ms | Accum ms | Total ms | Bottleneck |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 0.043 | 0.037 | 18.784 | 0.248 | 16.738 | 0.321 | 36.171 | gate/up |
| 1 | 0.043 | 0.036 | 18.592 | 0.256 | 16.777 | 0.323 | 36.026 | gate/up |
| 2 | 0.043 | 0.038 | 18.738 | 0.247 | 16.744 | 0.322 | 36.132 | gate/up |
| 3 | 0.043 | 0.015 | 14.144 | 0.251 | 14.531 | 0.331 | 29.314 | down |
| 14 | 0.043 | 0.020 | 14.186 | 0.252 | 14.664 | 0.330 | 29.495 | down |

| Run | Achieved rows/s | Corrected steady bound | Slowest stage | Slowest service ms | Hash | Read |
| --- | ---: | ---: | --- | ---: | --- | --- |
| Default | 209.036 | 237.492 | stage0 | 2,155.858 | `fnv64:5c9c39e9a1665737` | baseline |
| P2 skip aux writes | 210.999 | 237.992 | stage0 | 2,151.329 | `fnv64:5c9c39e9a1665737` | previous best |
| Slice-tile8 gate/up | 631.672 | 741.444 | stage0 | 690.545 | `fnv64:5c9c39e9a1665737` | current best |

## Slice-Down-Tile8 Attempt

With `DS4_CUDA_MOE_SLICE_TILE8=1`, the remaining routed-MoE time is split
between gate/up and down. A bounded `DS4_CUDA_MOE_SLICE_DOWN_TILE8=1` path was
added to reuse the same per-expert tile descriptors for down projection. It is
finite and hash-stable, but it regresses the down projection and full pipeline.

| Layer | Queue ms | Pointer ms | Gate/up ms | Quantize ms | Down ms | Accum ms | Total ms | Bottleneck |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 0.043 | 0.037 | 18.725 | 0.250 | 21.185 | 0.321 | 40.560 | down |
| 1 | 0.046 | 0.051 | 18.711 | 0.248 | 21.742 | 0.318 | 41.116 | down |
| 2 | 0.041 | 0.037 | 18.757 | 0.247 | 21.163 | 0.322 | 40.567 | down |
| 3 | 0.045 | 0.020 | 14.158 | 0.250 | 17.454 | 0.325 | 32.252 | down |
| 14 | 0.046 | 0.020 | 14.065 | 0.250 | 17.387 | 0.326 | 32.094 | down |

| Run | Achieved rows/s | Corrected steady bound | Slowest stage | Slowest service ms | Hash | Read |
| --- | ---: | ---: | --- | ---: | --- | --- |
| Slice-tile8 gate/up | 631.672 | 741.444 | stage0 | 690.545 | `fnv64:5c9c39e9a1665737` | current best |
| Slice-tile8 + slice-down-tile8 | 559.396 | 659.235 | stage0 | 776.658 | `fnv64:5c9c39e9a1665737` | rejected, down got slower |

## Direct Sum6 Down Attempt

A narrower direct top-6 accumulation path was tested with
`DS4_CUDA_MOE_SLICE_TILE8=1` and `DS4_CUDA_MOE_DIRECT_SUM6_DOWN=1`. The intent
was to skip materializing six separate down rows and the follow-up sum kernel.
The sum step disappeared, but the slot-serial down kernel was much slower than
the existing P2 slices down path.

| Layer | Gate/up ms | Down ms before | Down ms direct-sum6 | Accum ms direct-sum6 | Total ms direct-sum6 | Bottleneck |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 18.774 | 16.436 | 62.954 | 0.001 | 82.038 | down |
| 1 | 18.641 | 16.786 | 63.396 | 0.001 | 82.351 | down |
| 2 | 18.795 | 16.809 | 63.362 | 0.001 | 82.468 | down |
| 3 | 14.041 | 14.563 | 57.148 | 0.001 | 71.478 | down |
| 14 | 14.117 | 14.653 | 62.919 | 0.001 | 77.325 | down |

| Run | Achieved rows/s | Corrected steady bound | Slowest stage | Slowest service ms | Hash | Read |
| --- | ---: | ---: | --- | ---: | --- | --- |
| Slice-tile8 gate/up | 631.672 | 741.444 | stage0 | 690.545 | `fnv64:5c9c39e9a1665737` | current best |
| Slice-tile8 + direct-sum6 down | 408.047 | 467.907 | stage0 | 1,094.234 | `fnv64:5c9c39e9a1665737` | rejected, down got much slower |

## Prompt-Decode Smoke

The B=512/mb16 slice-tile8 handoff now has matching PP=1 and PP=N logits:

| Evidence | Value |
| --- | --- |
| PP=1 export | `fixtures/pipeline_outputs/dsv4_slice_tile8_pp1_output_export_20260516.example.json` |
| PP=N export | `fixtures/pipeline_outputs/dsv4_slice_tile8_ppn_output_export_20260516.example.json` |
| Parity artifact | `fixtures/pipeline_parity/dsv4_slice_tile8_cross_spark_ppn_passed_20260516.example.json` |
| PP=1 logits hash | `fnv64:5c9c39e9a1665737` |
| PP=N logits hash | `fnv64:5c9c39e9a1665737` |
| PP=1 output-head hash | `fnv64:6cf5f3c6e011e527` |
| Prompt-decode smoke | `fixtures/prompt_decode_smoke/dsv4_b512_slice_tile8_prompt_decode_smoke_20260516.example.json` |

The smoke preserves the measured B=512 rows/s (`631.672`) and corrected
steady-state bound (`741.444`). It deliberately keeps
`production_generation_eligible=false`: finite logits and output-head hashes are
present, but committed token ids and `token_hash` are not, because the runtime
probe does not yet print an argmax/sampling token id. The repo-owned
`ds4-token-commit-export-v1` contract and validator are ready; an eligible
prompt-decode smoke must reference that export and have matching optimized
kernel flags with the parity artifact.

## B=512 End-To-End Decode

The batch-stack probe now has a minimal top-1 token commit path behind
`DS4_CUDA_STACK_PROBE_BATCH_HEAD=1`. This is not a kernel optimization: it runs
the full batch output head for all 512 rows, reads back committed token ids, and
emits `token_hash`. The real decode-only short-output path is therefore lower
than the finite-logits proof because stage2 becomes the batch-head/top-1
bottleneck.

| Case | Output target | Result | End-to-end output tok/s | Decode-only rows/s | Token hash | Blocker |
| --- | ---: | --- | ---: | ---: | --- | --- |
| Decode only, B=512/mb16 | 1 | finite committed tokens | 260.973 | 261.082 | `fnv64:c73fd75838d4c57f` | none |
| Decode only, constrained candidate commit, B=512/mb16 | 1 | finite committed tokens | 629.183 | 630.453 | `fnv64:7b018999c9d460f7` | none |
| Shared prefix hit + compact suffix, full vocab | 1 | finite committed tokens | 264.586 | 264.706 | `fnv64:4dbeb5a7e01d8828` | none |
| Shared prefix miss + compact suffix, full vocab | 1 | finite committed tokens | 251.016 | 264.706 | `fnv64:4dbeb5a7e01d8828` | none |
| Shared prefix hit + compact suffix, constrained numeric IDs | 1 | finite committed tokens | 648.332 | 650.255 | `fnv64:0f3476a5eb4356b4` | production eligibility false: row-token suffix probe, not production shared-prefix KV service |
| Shared prefix + compact suffix | 4 | committed-token KV loop artifact | 619.840 | 630.453 | `fnv64:dc1f01b7ef50f542` | production eligibility stays false until Spark0 reruns the new runtime hook |
| Shared prefix + compact suffix | 8 | committed-token KV loop artifact | 624.381 | 630.453 | `fnv64:a6aa18faed631e12` | production eligibility stays false until Spark0 reruns the new runtime hook |
| Unique prefix control | 1 | blocked | 0.000 | 0.000 |  | missing B=512 unique-prefix prefill runner |

Shared-prefix 1-token split:

| Metric | Hit/fork | Miss/prepare |
| --- | ---: | ---: |
| prefix_prepare_ms | 0.000 | 1673.792 |
| prefix_load_or_fork_ms | 0.000 | 0.000 |
| suffix_prefill_ms | 30947.532 | 30947.532 |
| suffix_prefill_tokens_per_s | 264.706 | 264.706 |
| token_commit_ms | 14.083 | 14.083 |

Token-commit profile:

| Mode | Stage2 hidden ms | Output head ms | Top1/argmax ms | Result collection ms | Bottleneck |
| --- | ---: | ---: | ---: | ---: | --- |
| Full-vocab batch head | 632.808 | 1125.538 | 0.189 | 28.297 | full batch output projection |
| Constrained candidate commit | not instrumented | not instrumented | 3.868 | 32.614 | stage compute after full-vocab head removal |

Constrained-output benchmark:

| Case | Candidate kind | Output target | End-to-end output tok/s | Commit mode | Production eligible |
| --- | --- | ---: | ---: | --- | --- |
| Shared-prefix hit, numeric IDs | `numeric_ids` | 1 | 648.332 | `constrained_vocab_cpu_top1` | false |
| Shared-prefix hit, numeric IDs | `numeric_ids` | 4 | 619.840 | `constrained_vocab_cpu_top1` | false |
| Shared-prefix hit, numeric IDs | `numeric_ids` | 8 | 624.381 | `constrained_vocab_cpu_top1` | false |
| Shared-prefix hit, full-vocab control | `full_vocab` | 1 | 264.586 | `full_vocab_batch_head` | false |

The constrained 1-token row is a live Spark0->Spark1->Spark2 row-token suffix
probe with committed IDs. The 4/8-token rows are KV-loop artifacts derived from
the one-step constrained lane until Spark0 reruns the production shared-prefix
hit/fork runtime hook. The constrained-output validator requires an explicit
candidate set, passed parity artifact, token hash, committed IDs, and matching
optimized kernel flags before any artifact can be considered for production
eligibility.

Artifacts:

- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_slice_tile8_batch_head_token_commit.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_slice_tile8_full_vocab_token_profile.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_slice_tile8_constrained_token_commit.example.json`
- `fixtures/stage_handoff/spark012_b512_shared_prefix_compact_suffix_full_vocab_20260516.example.json`
- `fixtures/stage_handoff/spark012_b512_shared_prefix_compact_suffix_constrained_commit_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_decode_only_1_token_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_decode_only_1_token_constrained_commit_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_hit_short_suffix_1_token_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_miss_short_suffix_1_token_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_hit_constrained_numeric_1_token_20260516.example.json`
- `fixtures/constrained_output/ds4_b512_constrained_numeric_hit_1_token_20260516.example.json`
- `fixtures/constrained_output/ds4_b512_constrained_numeric_hit_4_token_20260516.example.json`
- `fixtures/constrained_output/ds4_b512_constrained_numeric_hit_8_token_20260516.example.json`
- `fixtures/constrained_output/ds4_b512_full_vocab_control_hit_1_token_20260516.example.json`
- `fixtures/token_commit_profile/ds4_b512_full_vocab_token_commit_profile_20260516.example.json`
- `fixtures/token_commit_profile/ds4_b512_constrained_token_commit_profile_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_short_suffix_1_token_blocked_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_short_suffix_4_token_blocked_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_short_suffix_4_token_kv_loop_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_short_suffix_8_token_blocked_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_shared_prefix_short_suffix_8_token_kv_loop_20260516.example.json`
- `fixtures/end_to_end_decode/ds4_b512_unique_prefix_control_blocked_20260516.example.json`

## Current Blocker

MTP remains paused as a speed path. The latest accepted-token run is not an
acceptance failure: baseline greedy is 14.65 t/s, MTP draft=2 is 2.00 t/s, and
acceptance is 21/21. The verifier-economics artifact shows the real blocker:
target evaluation is still paid almost token-for-token. The target-suffix K=2
prototype makes the intended API explicit and can fuse output-head accounting
from 21 invocations to 11, but it still delegates to serial target decode with
`staged_kv_ready=false`, so `target_eval_ms` remains dominant.

Exact next MTP code change: replace the delegated body of
`target_suffix_verify_k2(...)` with a real staged target suffix pass that
verifies two draft positions in one target invocation, preserves rollbackable
KV/cache state, commits the accepted prefix, and returns continuation logits
without a second full target eval.

The base pipeline now exceeds 250 rows/s and has PP=1/PP=N logits parity.
Pipeline bubble is effectively gone at B=512/mb16 and transfer is not material.
The slice-tile8 gate/up path cut stage0 service time from about 2,151 ms to
about 691 ms. The first slice-down tile attempt did not help: it raised layer 2
down from about 16.8 ms to about 21.2 ms and dropped the full pipeline from
631.672 to 559.396 rows/s. The direct-sum6 attempt is worse: it serializes six
down projections per row, raises layer 2 down to about 63.4 ms, and drops the
full pipeline to 408.047 rows/s.

Committed-token decode-only now catches the finite-logits path when the task can
declare an exact constrained candidate set: 629.183 tok/s end-to-end versus
631.672 finite-logits rows/s. The full-vocab token commit profile shows the
old 260.973 tok/s path was capped by the 512-row output projection
(~1.12 s/microbatch), not readback or top-1.

The B=512 shared-prefix compact-suffix 1-token hook now runs with explicit
per-row suffix token IDs and committed token hashes. It does not cross 300 tok/s
on the full-vocab path because stage2 still spends about 1.73 s per B=512
microbatch in the full batch-head projection path. The same shared-prefix
1-token shape with constrained numeric IDs reaches 648.332 tok/s. Prefix miss
adds only about 1.67 s one time for the measured 64-token shared prefix. The
4/8-token KV-loop artifacts exist, but production eligibility stays false until
Spark0 reruns the new runtime hook with real shared-prefix hit/fork inputs and
measured per-step timings/token hashes. For unconstrained natural-language
commit, the next kernel target remains the full-vocab batch output projection;
for structured short outputs, the constrained candidate commit path is the
current fast lane.

Latest handoff artifacts:

- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_tile4.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_skipaux.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_slice_tile8.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_slice_down_tile8.example.json`
- `fixtures/stage_handoff/spark012_b512_tcp_resident_mb16_p2_direct_sum6_down.example.json`
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
- `fixtures/moe_p2_inner_profile/spark0_p2_inner_b512_mb16_slice_tile8.example.json`
- `fixtures/moe_p2_inner_profile/spark0_p2_inner_b512_mb16_slice_tile8_presum6.example.json`
- `fixtures/moe_p2_inner_profile/spark0_p2_inner_b512_mb16_slice_down_tile8.example.json`
- `fixtures/moe_p2_inner_profile/spark0_p2_inner_b512_mb16_direct_sum6_down.example.json`
