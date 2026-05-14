# Expert Transition Affinity: Spark0 Partial Dump

Date: 2026-05-14

This captures the first real `P(next expert | current expert)` measurement from
DS4 `ffn_moe_topk` route dumps. The run is partial: Spark0 produced layers
`0..16` before the older local `ds4` CUDA path timed out while lazy-loading a
later MoE full slab. The partial sample is still useful because it contains
`17` adjacent routed layers, `2048` rows per layer, and `1,179,648` adjacent
expert-pair transitions.

## Setup

- Host: Spark0
- Runtime: local `/home/spark0/src/ds4` at `antirez/ds4@3630e64` with local
  CUDA edits
- Model:
  `/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf`
- Prompt: `scripts/make_ds4_expert_fuzz_prompt.py --count 100`
- Dump knobs:

```bash
DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
DS4_METAL_GRAPH_DUMP_PREFIX=/tmp/ds4_transition_affinity_20260514T1025Z/topk \
DS4_METAL_GRAPH_DUMP_NAME=ffn_moe_topk \
DS4_METAL_GRAPH_DUMP_LAYER=all \
DS4_METAL_GRAPH_DUMP_POS=0 \
./ds4 -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  --prompt-file /tmp/ds4_transition_affinity_20260514T1025Z/prompt.txt \
  --cuda --nothink --temp 0 -n 1
```

Spark0's local tree did not yet include the startup-skip guard in `ds4.c`, so
that one-line guard was added before the run. This was a Spark0 working-copy
fix only; the repo already tracks the documented upstream patch path.

The run stopped at layer 17 with:

```text
CUDA model range copy failed for moe_gate at 448.00 MiB
CUDA model range alloc failed for moe_gate (528.00 MiB)
CUDA model arena alloc failed for moe_up (1792.00 MiB chunk)
```

That failure is the known full-slab residency problem, not an analyzer failure.

## Transition-Affinity Result

Command:

```bash
python3 scripts/analyze_ds4_expert_transitions.py \
  --dump-dir /private/tmp/ds4_transition_affinity_20260514T1025Z \
  --pos 0 --topk 6 --experts 256 --logical-lanes 32 --sparks 8 \
  --json-out /private/tmp/ds4_transition_affinity_20260514T1025Z/expert_transition_affinity_compact.json
```

Summary:

| Metric | Value |
| --- | ---: |
| Layers captured | `17` |
| Adjacent layer pairs | `16` |
| Rows per layer | `2048` |
| Expert-pair transitions | `1,179,648` |
| Invalid expert IDs | `0` |
| Weighted top-1 next-expert mass | `4.54%` |
| Weighted top-4 next-expert mass | `14.20%` |
| Weighted top-8 next-expert mass | `23.09%` |
| Weighted top-16 next-expert mass | `35.87%` |
| Weighted top-32 next-expert mass | `52.55%` |
| Weighted normalized entropy | `86.74%` |
| Same-Spark rate, `expert_id % 32` | `12.67%` |
| Same-Spark rate, balanced affinity table | `45.77%` |
| Cross-Spark transition reduction | `37.90%` |

Layer-pair same-Spark ranges:

| Map | Min | Median | Mean | Max |
| --- | ---: | ---: | ---: | ---: |
| `expert_id % 32` | `11.41%` | `12.69%` | `12.67%` | `13.77%` |
| Affinity table | `28.62%` | `47.11%` | `45.77%` | `55.36%` |

## Interpretation

The conditional distribution is not deterministic. A current expert's single
most likely next expert averages only about `4.5%` of mass, and entropy remains
high. But the mass is still structured enough that balanced layer-specific
placement improves locality dramatically.

The key result is the routing impact:

```text
expert_id % 32 local transitions: 12.67%
affinity table local transitions: 45.77%
```

That means the current modulo map would send about `87.33%` of adjacent
expert-pair transitions off-Spark on this partial sample. The simple greedy
affinity table would cut that to about `54.23%`, a `37.90%` reduction in
cross-Spark transitions before any graph-partitioning optimization.

This supports making expert ownership table-driven:

```text
owner_spark = expert_owner_table[layer][expert_id]
```

The runtime complexity should stay flat. The table can be generated offline
from route dumps and updated when better route traces arrive.

## Queue Occupancy Check

The same partial dump still matches the earlier queue-depth story:

| Batch tokens | Active experts | Max depth | Mean active depth | P90 depth | Cap-6 pair speedup |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 55.0 | 8.0 | 1.75 | 3.0 | 1.68 |
| 32 | 82.0 | 16.0 | 2.34 | 4.0 | 2.18 |
| 64 | 114.0 | 31.0 | 3.37 | 7.0 | 2.84 |
| 100 | 133.0 | 48.0 | 4.51 | 10.0 | 3.39 |
| 128 | 143.0 | 61.0 | 5.37 | 12.0 | 3.69 |
| 256 | 166.0 | 121.0 | 9.25 | 21.0 | 4.50 |
| 512 | 185.0 | 239.5 | 16.61 | 38.0 | 5.09 |

## Next Steps

1. Refresh Spark0's `ds4` source to the current full probe patch chain so route
   dumps can reach all 43 layers without full-slab lazy-load timeouts.
2. Generate full-layer transition tables for `8` logical Sparks.
3. Compare greedy affinity against a graph partitioner with per-layer balance
   constraints.
4. Feed the table into the distributed expert-queue design as data, not code
   branches.
