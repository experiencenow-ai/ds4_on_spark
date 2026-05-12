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
- `docs/antirez-patches/ds4-3630e64-cuda-multi-model-cache.patch` (recommended when using any CUDA weight caching)

## Math validation (host-side)

The Q4_K dot math in the patch is derived from ggml’s `dequantize_row_q4_K` logic (scale/min unpacking + nibble unpacking). This repo includes a CPU-only verifier that checks the two formulations match (no CUDA required):

- `scripts/verify_antirez_ds4_q4k_dot_math.py`
- `fixtures/quant/q4k_llamacpp_b9110_rowdot_fixture.json` (ggml-org/llama.cpp `b9110` vectors)

Run:

```bash
python3 scripts/verify_antirez_ds4_q4k_dot_math.py
```

Unit test hook:

```bash
python3 -m unittest tests/q4k_llamacpp_fixture_test.py
```

## Remaining correctness risks (not solved here)

- **First-draft agreement** is still a separate problem: “finite logits” is necessary but not sufficient.
- The patch intentionally leaves the optimized CUDA MoE down fast path (`Q2_K`) unchanged; `Q4_K` uses a slower fallback until a dedicated kernel is validated.
- Multi-model caching is still incomplete: the patch in this repo keys ranges by `(model_map, fd, offset)`, but a fully robust cache likely also needs `bytes` (or an equivalent range key) rather than assuming a single global map.
- Even with the sidecar map treated as “secondary”, CUDA caching structures must not be keyed only by `offset`; otherwise trunk and sidecar offsets can alias under `DS4_CUDA_WEIGHT_CACHE=1` and produce silent wrong-weight reads.

## Next experiment (recommended)

1) Use `antirez/ds4` (patched) as the **oracle** to export intermediate tensors/logits for a single prompt + `gamma=1` draft.
2) Add a llama.cpp Spark/CUDA probe to emit the same intermediate tensors and diff them against the oracle before running acceptance sweeps.

Practical first step: have both probes emit the same one-token JSON schema and run the strict diff tool:

- `python3 scripts/diff_mtp_one_token_draft_probe.py --a /path/to/oracle_probe.json --b /path/to/candidate_probe.json --json`

This repo includes an additional `antirez/ds4@3630e64` patch to make the oracle JSON capture concrete:

- `docs/antirez-patches/ds4-3630e64-mtp-one-token-json-probe.patch`
  - adds `--dump-mtp-one-token-json` to `ds4` (emits a single JSON object to stdout)
  - captures intermediate `*_fnv64` fingerprints for the MTP draft path

Spark runner hook (no fetch/build; executes whatever is installed on Spark):

```bash
REMOTE_MTP_ONE_TOKEN_ENV="ALLOW_RUN=1" \
REMOTE_MTP_ONE_TOKEN_CMD="/abs/path/to/ds4 --cuda -m /abs/trunk.gguf --mtp /abs/DeepSeek-V4-Flash-MTP-*.gguf -p 'Hello.' --dump-mtp-one-token-json" \
scripts/run_mtp_one_token_draft_probe_spark.sh spark0@<spark-host>
```
