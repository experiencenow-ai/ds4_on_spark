# Expert Scaling Proof Plan

This project needs to prove expert queues with measurements, not just routing
intuition. The proof should be staged so every step isolates one uncertainty.

## What Is Already True

DeepSeek V4 Flash routes each token through 43 layers. In each routed layer,
the token selects 6 experts out of 256. A batch of 100 independent decode rows
therefore creates 600 expert assignments per layer.

Uniform routing would average only `100 * 6 / 256 = 2.34` rows per expert, but
the observed Spark0 route dump is non-uniform. The first fuzz probe recorded in
`docs/expert-queue-fuzz-spark0-2026-05-12.md` showed median active depth of
`4.41`, P90 depth of `10`, and a simple cap-6 pair-work estimate around `3.38x`
for a 100-row batch.

## New Kernel A/B: Valid Prefill Activations

The current antirez CUDA path already sorts token/expert pairs and builds expert
tiles for `n_tokens > 1`. This gives us a direct A/B on valid model activations:
same GGUF, same prompt, same hidden states, same selected experts, only the MoE
kernel strategy changes.

Command shape:

```bash
cd /home/spark0/src/ds4

DS4_CUDA_MOE_PROFILE=1 \
./ds4-bench \
  -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  --chat-prompt-file bench/promessi_sposi.txt \
  --cuda \
  --ctx-start 2048 \
  --ctx-max 2048 \
  --step-incr 2048 \
  --gen-tokens 1 \
  --csv /tmp/ds4_moe_profile_default.csv \
  > /tmp/ds4_moe_profile_default.out \
  2> /tmp/ds4_moe_profile_default.err
```

Fallback variants:

```bash
DS4_CUDA_MOE_PROFILE=1 DS4_CUDA_MOE_NO_EXPERT_TILES=1 ...
DS4_CUDA_MOE_PROFILE=1 DS4_CUDA_MOE_NO_EXPERT_TILES=1 DS4_CUDA_MOE_NO_P2=1 ...
```

Summarize:

```bash
python3 scripts/analyze_ds4_moe_profile.py \
  /tmp/ds4_moe_profile_default.err \
  /tmp/ds4_moe_profile_no_tiles.err \
  /tmp/ds4_moe_profile_no_tiles_no_p2.err
```

Spark0 median per-layer MoE timings for `tokens=2048`:

| Variant | Total MoE | Gate/up | Down | Prefill TPS |
| --- | ---: | ---: | ---: | ---: |
| expert tiles | 79.938 ms | 40.658 ms | 38.232 ms | 307.28 |
| no expert tiles, P2 sorted | 527.876 ms | 463.543 ms | 61.671 ms | 76.68 |
| no expert tiles, no P2 | 932.192 ms | 874.353 ms | 55.293 ms | 46.14 |

This proves the expert-tiled path can turn real routed batches into a large
kernel-level gain. It is not yet a decode scheduler proof because prefill gives
the runtime a natural multi-token batch.

## Artificial But Valid Scaling Fixtures

Use two fixture classes:

1. **Route-only replay fixture**
   - Input: real `ffn_moe_topk` dumps from antirez DS4.
   - Artificial part: resample rows into batch sizes 16, 32, 64, 100, 128, 256.
   - Validity: every row is a real model route from a real prompt/layer.
   - Output: active expert count, queue depths, cap-N pair-work estimates.

2. **Hidden-state replay fixture**
   - Input: real `ffn_norm`, `ffn_moe_topk`, and `ffn_moe_weights_scaled`
     dumps for many positions/layers.
   - Artificial part: pack rows from independent positions into one
     decode-like `n_tokens = B` batch.
   - Validity: expert IDs, weights, and hidden states all came from DS4.
   - Output: compare tiled batched MoE against running the same rows one at a
     time. This removes attention, KV, sampling, and networking from the proof.

Passing the hidden-state replay gate is the closest thing to a sure answer
before implementing a full continuous decode scheduler.

## Full Decode Gate

After the microbench passes, add a decode replay that keeps `B` independent
session states at the same generation step and calls the batched FFN/MoE path
with `n_tokens = B`.

Success criteria:

- batched MoE produces numerically close outputs to B independent one-token MoE
  calls;
- MoE sublayer speedup is at least `3x` at batch 100 or explains why not;
- full per-token decode wall time improves at least `2x` before cross-Spark
  routing, or the non-MoE bottleneck is identified;
- cross-Spark routing is tested only after single-Spark batching proves the
  MoE path is actually the bottleneck being relieved.

## Cross-Spark Expectation

Routing between Sparks can reduce time-to-output only if one of these is true:

- different Sparks own disjoint expert shards and communication is cheaper than
  local expert work avoided;
- or each Spark runs a separate queued batch lane and the request router keeps
  all devices saturated.

The first route needs expert-parallel communication benchmarks. The second route
is easier and should be attempted first: it increases aggregate throughput, but
does not reduce latency for a single prompt unless batching delay is already the
dominant wait.
