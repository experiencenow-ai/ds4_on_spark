# Expert Queue Batch Sweep: Spark0 / antirez DS4

Date: 2026-05-12

This is the second expert-queue proof after
`docs/expert-queue-fuzz-spark0-2026-05-12.md`. The fuzz probe established that
real DS4 routes create useful expert queue depths. This sweep measures whether
the current CUDA MoE kernels turn valid batched rows into actual speed.

## Setup

- Host: `spark0@aitopatom-9ab9.local`
- Runtime: current `antirez/ds4` CUDA build
- Model:
  `/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf`
- Prompt source: `bench/promessi_sposi.txt` rendered as a no-thinking chat
  prompt by `ds4-bench`
- Profile flag: `DS4_CUDA_MOE_PROFILE=1`
- Variants:
  - `default`: expert tiles enabled
  - `no_tiles`: `DS4_CUDA_MOE_NO_EXPERT_TILES=1`

The sweep can be reproduced with:

```bash
OUT_DIR=/tmp/ds4_moe_batch_sweep_20260512 \
scripts/run_ds4_moe_batch_sweep_spark.sh spark0@aitopatom-9ab9.local
```

The runner sets `DS4_METAL_PREFILL_CHUNK=<batch_rows>` for each frontier so
batch sizes above 2048 remain one real graph/MoE batch instead of being silently
split into the runtime's default 2048-token chunks. Set `SET_PREFILL_CHUNK=0`
only when intentionally measuring the default chunking policy.

Then copy the logs locally and summarize with:

```bash
python3 scripts/analyze_ds4_moe_profile.py \
  /tmp/default_16.err /tmp/default_32.err /tmp/default_64.err \
  /tmp/default_100.err /tmp/default_128.err /tmp/default_256.err \
  /tmp/default_512.err /tmp/default_1024.err /tmp/default_2048.err \
  /tmp/no_tiles_16.err /tmp/no_tiles_32.err /tmp/no_tiles_64.err \
  /tmp/no_tiles_100.err /tmp/no_tiles_128.err /tmp/no_tiles_256.err \
  /tmp/no_tiles_512.err /tmp/no_tiles_1024.err /tmp/no_tiles_2048.err
```

## MoE Kernel Results

Median per-layer CUDA MoE timings:

| Batch rows | Tiled MoE ms/layer | No-tile MoE ms/layer | Tile vs no-tile | Serial one-token estimate | Tiled vs serial | Prefill TPS tiled | Prefill TPS no-tile |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 3.616 | 6.281 | 1.74x | 5.712 | 1.58x | 13.00 | 15.78 |
| 32 | 5.409 | 11.124 | 2.06x | 11.488 | 2.12x | 28.55 | 25.71 |
| 64 | 8.540 | 20.238 | 2.37x | 22.912 | 2.68x | 54.59 | 38.28 |
| 100 | 11.393 | 29.929 | 2.63x | 35.800 | 3.14x | 74.41 | 46.67 |
| 128 | 8.892 | 37.598 | 4.23x | 45.952 | 5.17x | 110.40 | 54.19 |
| 256 | 13.504 | 70.979 | 5.26x | 91.392 | 6.77x | 166.31 | 64.64 |
| 512 | 22.913 | 137.059 | 5.98x | 182.784 | 7.98x | 262.24 | 73.46 |
| 1024 | 41.674 | 266.820 | 6.40x | 367.616 | 8.82x | 290.08 | 75.71 |
| 2048 | 79.546 | 526.384 | 6.62x | 735.232 | 9.24x | 315.82 | 76.93 |

`Serial one-token estimate` is `batch_rows * median(tokens=1 MoE ms/layer)`
from the same process family. It estimates the cost of sending the same number
of rows through the one-token decode MoE path one at a time.

Large tiled-only checks with `DS4_METAL_PREFILL_CHUNK=<batch_rows>`:

| Batch rows | Tiled MoE ms/layer | Tiled MoE ms/row, 43 layers | Prefill TPS |
| ---: | ---: | ---: | ---: |
| 2048 | 79.546 | 1.670 | 315.82 |
| 4096 | 155.339 | 1.631 | 289.14 |
| 8192 | 306.202 | 1.607 | 276.77 |

## Interpretation

At the user-relevant `B=100` point, the real expert-tiled CUDA MoE path is:

- `3.14x` faster than serial one-token MoE work;
- `2.63x` faster than the no-tile batched fallback;
- still using valid DS4 activations, routes, weights, and GGUF tensors.

This supports a credible `3x-4x` MoE-side gain if the decode scheduler can pack
roughly 100 independent rows into the existing `n_tokens > 1` MoE kernel path.
The larger-batch tail shows that the expert-tile path keeps improving as route
queues deepen.

For pure throughput work, larger batches help: per-row MoE cost falls from
`4.899 ms` at `B=100` to `2.268 ms` at `B=256`, `1.924 ms` at `B=512`, and
about `1.6-1.7 ms` at `B=2048-8192`. The marginal MoE gain beyond roughly
`B=2048` is small, so the throughput scheduler should treat `B=256-1024` as
the first practical batch lane and `B=2048+` as a bulk/offline lane, not as the
default interactive policy.

This still does not prove a `3x-4x` full decode speedup. The single-token decode
benchmark is about `14-15 tok/s`, or roughly `67-71 ms/token`. The one-token MoE
profile accounts for roughly `43 layers * 0.358 ms = 15.4 ms/token` of that.
At `B=100`, tiled MoE is roughly `43 * 11.393 / 100 = 4.9 ms/row`, saving about
`10.5 ms/row` in the MoE component before considering batching gains or losses
in attention, shared experts, output projection, sampling, and scheduling.

The next gate is therefore a hidden-state replay fixture: pack real `ffn_norm`,
`ffn_moe_topk`, and `ffn_moe_weights_scaled` rows from independent positions
into decode-shaped batches and compare batched MoE outputs against independent
one-row MoE outputs. Passing that gate would prove the MoE sublayer scaling in
a decode-shaped workload without waiting for the full continuous-batching
server.

## Imatrix Model Status

The improved antirez `q2-imatrix` GGUF is staged on Spark0:

- path:
  `/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix.gguf`
- size: `81G`
- sha256:
  `efc7ed607ff27076e3e501fc3fefefa33c0ed8cf1eff483a2b7fdc0c2e616668`

This is expected to improve quality rather than change expert-queue scaling.
