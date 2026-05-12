---
title: "antirez/ds4 CUDA: Q4_K MTP sidecar breakthrough (2026-05-12)"
---

# antirez/ds4 CUDA: Q4_K MTP sidecar breakthrough (2026-05-12)

Goal: make the `antirez/deepseek-v4-gguf` DeepSeek V4 Flash MTP sidecar usable on the **Spark/Linux CUDA** path, using `antirez/ds4` as the concrete execution reference.

## Spark0 finding (why stock CUDA broke)

When running `antirez/ds4` with the DS4-tuned sidecar:

- sidecar file: `DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf`
- the routed-MoE down experts in the MTP sidecar are **`Q4_K`** (not `Q2_K`)
- upstream `routed_moe_launch(...)` on CUDA rejected anything except:
  - gate/up: `IQ2_XXS`
  - down: `Q2_K`

So the CUDA MTP draft path failed inside the routed-MoE layer before draft logits could be trusted.

## Patch (in this repo)

This repo ships a patch against `antirez/ds4@3630e64` that addresses the two immediate CUDA blockers:

1) **Q4_K routed-MoE down fallback**
   - adds a `Q4_K` dot path for the f32 fallback kernels
   - allows `down_type == Q4_K` to proceed (while keeping the optimized Q2_K fast path unchanged)
2) **Secondary model-map support for sidecars**
   - prevents the sidecar `model_map` from resetting the global trunk CUDA mapping / fd-cache owner
   - routes sidecar ranges through lazy `cuda_model_range_ptr(...)` staging without the trunk fd-cache

Patch file:

- `docs/antirez-patches/ds4-3630e64-cuda-mtp-q4k-and-sidecar-map.patch`

## Math validation (host-side)

The Q4_K dot math in the patch is derived from ggml’s `dequantize_row_q4_K` logic (scale/min unpacking + nibble unpacking). This repo includes a CPU-only verifier that checks the two formulations match (no CUDA required):

- `scripts/verify_antirez_ds4_q4k_dot_math.py`

Run:

```bash
python3 scripts/verify_antirez_ds4_q4k_dot_math.py
```

## Remaining correctness risks (not solved here)

- **First-draft agreement** is still a separate problem: “finite logits” is necessary but not sufficient.
- The patch intentionally leaves the optimized CUDA MoE down fast path (`Q2_K`) unchanged; `Q4_K` uses a slower fallback until a dedicated kernel is validated.
- Multi-model caching is still incomplete: a real weight-cache should be keyed by `(model_map, fd, offset, bytes)` (or equivalent) rather than assuming a single global map.

## Next experiment (recommended)

1) Use `antirez/ds4` (patched) as the **oracle** to export intermediate tensors/logits for a single prompt + `gamma=1` draft.
2) Add a llama.cpp Spark/CUDA probe to emit the same intermediate tensors and diff them against the oracle before running acceptance sweeps.
