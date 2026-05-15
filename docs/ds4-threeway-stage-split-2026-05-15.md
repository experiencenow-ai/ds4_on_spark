# DS4 Three-Way Stage Split: Spark0/Spark1/Spark2

Date: 2026-05-15

This run used a patched `antirez/ds4@3630e64` stack probe with contiguous
stage ranges and explicit stage residency:

- Spark0: layers `[0,15)`, output head disabled
- Spark1: layers `[15,29)`, output head disabled
- Spark2: layers `[29,43)`, output head enabled

Each stage set `DS4_CUDA_STACK_PROBE_PRELOAD_STAGE=1`, which preloads all
layer tensors for that stage, including the routed expert slabs
`ffn_gate_exps`, `ffn_up_exps`, and `ffn_down_exps`. This removes the lazy
expert-weight load path from the timed stage execution.

Latest successful artifact root:

```text
/private/tmp/ds4-threeway-stage-20260515T083804Z
```

## B=64 working point

| Stage | Layers | Head | Preloaded | Best ms | Rows/s |
|---|---:|---:|---:|---:|---:|
| Spark0 | 15 | no | 454 tensors / 27.63 GiB | 800.373 | 79.963 |
| Spark1 | 14 | no | 434 tensors / 25.81 GiB | 656.242 | 97.525 |
| Spark2 | 14 | yes | 439 tensors / 26.33 GiB | 724.466 | 88.341 |

Steady-state pipeline bound is the slowest stage:

```text
64 rows / 800.373 ms = 79.963 rows/s
```

This is real DS4 CUDA layer-range execution on all three Sparks with owned-stage
expert residency. It is not yet correctness-proven end-to-end generation,
because boundary activations are synthetic and not transferred from stage to
stage.

The working source used `ds4-3630e64-cuda-explicit-stage-preload.patch` on top
of the stack-stage preload patch. The earlier stage preload called the generic
`ds4_gpu_cache_model_range(...)` demand-cache path for each chunk, so timeout
failures were reported as `lazy_moe_range_upload` even though the stage runner
was trying to preload. The explicit path allocates the final device-resident
range in the CUDA arena, reads through the pinned staging pool, and registers
the completed tensor range before timed execution.

Fixture:

```text
fixtures/threeway_stage_split/spark012_b64_explicit_preload_success.example.json
```

## B=128 attempt

Spark1 and Spark2 completed:

- Spark1 `[15,29)`: 830.993 ms, 154.032 rows/s
- Spark2 `[29,43)` plus head: 880.632 ms, 145.350 rows/s

Spark0 failed during stage preload before timing:

```text
ds4: CUDA model range copy failed for stack_stage_l2_t30 at 128.00 MiB: the launch timed out and was terminated
ds4: CUDA model range alloc failed for stack_stage_l2_t30 (528.00 MiB): the launch timed out and was terminated
```

The current working point is therefore B=64. The next code-level target is
making stage0 preload robust at B=128, likely by chunking exact tensor preloads
or preloading before graph activation buffers are allocated.

## Headless GPU requirement

Spark0/Spark1/Spark2 should stay headless for these measurements. Stopping
`gdm3` removed Xorg/gnome-shell GPU contexts from Spark0, and killing stale
`llama.cpp` RPC servers removed the last visible GPU contexts from Spark1 and
Spark2. After that cleanup, the B=64 three-way run completed on all three
nodes.

The next real performance target is not another preload proof. It is wiring
actual boundary activations through the pipeline so the same three stage ranges
process one DS4 request/batch end to end.
