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

Artifact root:

```text
/private/tmp/ds4-threeway-stage-20260515T060528Z
```

## B=64 working point

| Stage | Layers | Head | Preloaded | Best ms | Rows/s |
|---|---:|---:|---:|---:|---:|
| Spark0 | 15 | no | 454 tensors / 27.63 GiB | 807.656 | 79.242 |
| Spark1 | 14 | no | 434 tensors / 25.81 GiB | 738.516 | 86.660 |
| Spark2 | 14 | yes | 439 tensors / 26.33 GiB | 732.218 | 87.406 |

Steady-state pipeline bound is the slowest stage:

```text
64 rows / 807.656 ms = 79.242 rows/s
```

This is real DS4 CUDA layer-range execution on all three Sparks with owned-stage
expert residency. It is not yet correctness-proven end-to-end generation,
because boundary activations are synthetic and not transferred from stage to
stage.

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

## Follow-up residency finding

After repeated B=128 timeout attempts, Spark0 stopped completing even the
previously working B=16/B=64 stage0 preload. `nvidia-smi --gpu-reset` was
blocked because Xorg/gnome-shell own the device. The patch now moves stage
preload before graph allocation and exposes chunk/pacing knobs, but this Spark0
session still needs a clean CUDA reset or reboot before the next stage0 residency
test is meaningful.
