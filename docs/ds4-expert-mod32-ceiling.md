# DS4 Expert Mod-32 Ceiling

This is a network-free ceiling for the expert-parallel path. It answers one
specific question: if eight Sparks can keep 32 logical expert lanes resident
and we ignore off-card transfer cost, what aggregate throughput does the
current measured CUDA expert capacity imply?

It is not an end-to-end decode claim. It intentionally excludes network
routing, KV movement, scheduler stalls, output sampling, MTP overhead, and
full-stack weight residency failures.

## Assumptions

- DS4 has `43` routed layers.
- Each output token touches `topk=6` routed expert pairs per layer.
- The measured real MoE path on Spark0 is `159.7k` expert-pairs/s per Spark at
  `tokens=1024`.
- The measured FFN envelope on Spark0 is `24,007` token-layer/s per Spark.
- The measured batched layer envelope is roughly `409` tok/s per Spark before
  output head, KV bookkeeping, network routing, and scheduler overhead.
- The current warmed single-stream path is roughly `13.3` tok/s per Spark.
- For this ceiling only, eight Sparks scale linearly and network efficiency is
  `1.0`.

Formula:

```text
layer_pairs_per_output_token = layers * topk = 43 * 6 = 258
moe_only_tok_s_per_spark = pairs_per_s_per_spark / 258
moe_only_cluster_tok_s = moe_only_tok_s_per_spark * sparks
```

## Ceiling

Using `159.7k` measured routed expert-pairs/s per Spark:

| Envelope | Per Spark | 8-Spark Best Case |
| --- | ---: | ---: |
| MoE-only | `619 tok/s` | `4,952 tok/s` |
| FFN envelope | `558 tok/s` | `4,466 tok/s` |
| Batched layer envelope | `409 tok/s` | `3,272 tok/s` |
| Current single-stream decode | `13.3 tok/s` | `106 tok/s` |

The honest target band is therefore:

- `~5.0k tok/s` absolute MoE-only compute ceiling for eight Sparks.
- `~4.5k tok/s` once FFN wrapper work is included.
- `~3.3k tok/s` first serious batched full-layer target before network and
  runtime scheduling losses.

The real number should land below those because off-card expert activations and
returns must cross the 200 Gbps links. This file deliberately leaves that
penalty out so we have a clean optimistic bound.

## Expert Map

Use a logical lane:

```text
lane = expert_id % 32
spark_rank = floor(lane * num_sparks / 32)
```

For eight Sparks, each Spark owns four logical lanes and therefore 32 expert IDs
per layer. The lane map is:

| Lane | Spark | Expert IDs |
| ---: | ---: | --- |
| 0 | 0 | 0, 32, 64, 96, 128, 160, 192, 224 |
| 1 | 0 | 1, 33, 65, 97, 129, 161, 193, 225 |
| 2 | 0 | 2, 34, 66, 98, 130, 162, 194, 226 |
| 3 | 0 | 3, 35, 67, 99, 131, 163, 195, 227 |
| 4 | 1 | 4, 36, 68, 100, 132, 164, 196, 228 |
| 5 | 1 | 5, 37, 69, 101, 133, 165, 197, 229 |
| 6 | 1 | 6, 38, 70, 102, 134, 166, 198, 230 |
| 7 | 1 | 7, 39, 71, 103, 135, 167, 199, 231 |
| 8 | 2 | 8, 40, 72, 104, 136, 168, 200, 232 |
| 9 | 2 | 9, 41, 73, 105, 137, 169, 201, 233 |
| 10 | 2 | 10, 42, 74, 106, 138, 170, 202, 234 |
| 11 | 2 | 11, 43, 75, 107, 139, 171, 203, 235 |
| 12 | 3 | 12, 44, 76, 108, 140, 172, 204, 236 |
| 13 | 3 | 13, 45, 77, 109, 141, 173, 205, 237 |
| 14 | 3 | 14, 46, 78, 110, 142, 174, 206, 238 |
| 15 | 3 | 15, 47, 79, 111, 143, 175, 207, 239 |
| 16 | 4 | 16, 48, 80, 112, 144, 176, 208, 240 |
| 17 | 4 | 17, 49, 81, 113, 145, 177, 209, 241 |
| 18 | 4 | 18, 50, 82, 114, 146, 178, 210, 242 |
| 19 | 4 | 19, 51, 83, 115, 147, 179, 211, 243 |
| 20 | 5 | 20, 52, 84, 116, 148, 180, 212, 244 |
| 21 | 5 | 21, 53, 85, 117, 149, 181, 213, 245 |
| 22 | 5 | 22, 54, 86, 118, 150, 182, 214, 246 |
| 23 | 5 | 23, 55, 87, 119, 151, 183, 215, 247 |
| 24 | 6 | 24, 56, 88, 120, 152, 184, 216, 248 |
| 25 | 6 | 25, 57, 89, 121, 153, 185, 217, 249 |
| 26 | 6 | 26, 58, 90, 122, 154, 186, 218, 250 |
| 27 | 6 | 27, 59, 91, 123, 155, 187, 219, 251 |
| 28 | 7 | 28, 60, 92, 124, 156, 188, 220, 252 |
| 29 | 7 | 29, 61, 93, 125, 157, 189, 221, 253 |
| 30 | 7 | 30, 62, 94, 126, 158, 190, 222, 254 |
| 31 | 7 | 31, 63, 95, 127, 159, 191, 223, 255 |

Regenerate the numbers and map with:

```bash
python3 scripts/ds4_expert_mod32_ceiling.py --show-experts
```

For a different future node count:

```bash
python3 scripts/ds4_expert_mod32_ceiling.py --sparks 10 --show-experts
```
