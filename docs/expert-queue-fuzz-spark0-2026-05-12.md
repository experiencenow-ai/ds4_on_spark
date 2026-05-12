# Expert Queue Fuzz Probe: Spark0 / antirez DS4

Date: 2026-05-12

This records a first routing-occupancy probe for DeepSeek V4 Flash on Spark0
using the current `antirez/ds4` CUDA backend. The goal is to estimate whether
expert queues are deep enough to justify a batched decode scheduler.

## Setup

- Host: `spark0@aitopatom-9ab9.local`
- Backend: antirez DS4 CUDA graph backend
- Model:
  `/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf`
- Shape verified from source:
  - layers: 43
  - routed experts: 256
  - selected experts per token/layer: 6

The prompt was generated with:

```bash
python3 scripts/make_ds4_expert_fuzz_prompt.py \
  --count 100 \
  --output /tmp/ds4_expert_fuzz_prompt.txt
```

The top-k expert dump was produced on Spark0 with:

```bash
DS4_METAL_GRAPH_DUMP_PREFIX=/tmp/ds4_expert_fuzz_20260512T1335Z/topk \
DS4_METAL_GRAPH_DUMP_NAME=ffn_moe_topk \
DS4_METAL_GRAPH_DUMP_LAYER=all \
DS4_METAL_GRAPH_DUMP_POS=0 \
/home/spark0/src/ds4/ds4 \
  -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  --prompt-file /tmp/ds4_expert_fuzz_prompt.txt \
  --cuda --nothink --temp 0 -n 1
```

The run produced 43 `ffn_moe_topk` dump files. Each file contains
`2048 x 6` int32 expert ids for the first prefill chunk.

## Resampled Queue Estimate

The analyzer resampled token rows from each layer dump with 250 deterministic
trials per batch size:

```bash
python3 scripts/analyze_ds4_expert_queue_dump.py \
  --dump-dir /tmp/ds4_expert_fuzz_20260512T1335Z \
  --json-out /tmp/ds4_expert_fuzz_20260512T1335Z/resample_summary.json
```

Median layer-level results:

| Batch tokens | Active experts | Max depth | Mean active depth | P90 depth | Cap-6 pair speedup |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 60.0 | 6.0 | 1.60 | 3.0 | 1.59 |
| 32 | 88.0 | 10.0 | 2.18 | 4.0 | 2.13 |
| 64 | 116.0 | 20.0 | 3.31 | 7.0 | 2.84 |
| 100 | 136.0 | 30.5 | 4.41 | 10.0 | 3.38 |
| 128 | 146.0 | 39.0 | 5.26 | 12.0 | 3.67 |
| 256 | 170.0 | 76.0 | 9.04 | 21.0 | 4.47 |
| 512 | 191.0 | 150.0 | 16.08 | 39.0 | 5.08 |

`Cap-6 pair speedup` is a simple pair-work estimate:
`batch * 6 / sum(ceil(expert_depth / 6))`. It is not an end-to-end decode
speed prediction; it only asks how much expert pair work can be packed if an
expert tile handles up to six token rows.

## Interpretation

For 100 simultaneous decode-like rows, the uniform mean across all experts is
`100 * 6 / 256 = 2.34` pairs per expert. The observed routing is non-uniform:
the median active expert depth is `4.41`, P90 is `10`, and some layers have a
single expert around `78` rows in this resampled first-chunk prompt.

That confirms expert queues are real and often deeper than the all-expert
average. It does not support a clean 16x end-to-end speedup estimate from a
100-prompt batch. A more conservative first estimate for the routed-expert
pair work is roughly `3.4x` at batch 100 and `4.5x` at batch 256 if a cap-6
tile model is the right abstraction.

The next proof point is a decode-batch probe that captures `ffn_moe_topk` for
independent request states at the same generation step. This prefill-token
probe is useful for queue occupancy, but it is still not the final scheduler
measurement.
