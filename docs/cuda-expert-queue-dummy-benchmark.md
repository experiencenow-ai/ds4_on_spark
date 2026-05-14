# CUDA Expert Queue Dummy Benchmark

`ds4_expert_queue_dummy` is a repo-native CUDA benchmark for the expert-queue
proof path. It deliberately avoids model weights and MTP correctness. The goal
is to measure whether the data movement and queued expert matvec shape can scale
before coupling it to the full DS4 decode scheduler.

The benchmark allocates:

- token activations;
- per-expert gate/up/down float slabs;
- selected expert IDs for `tokens * topk` pairs;
- device pointer arrays for expert slices;
- routed mid activations and output rows.

It then runs a gate/up-style routed kernel followed by a down-style routed
kernel for `iterations` loops and reports timing plus rough movement bandwidth.
This is not a quality or logits benchmark. It is a CUDA movement/scheduling
fixture.

## Build

On Spark:

```bash
cmake -S . -B build-cuda -DDS4_ENABLE_CUDA=ON -DDS4_ENABLE_CLI=ON -DDS4_ENABLE_TESTS=ON
cmake --build build-cuda --parallel
```

The CMake CUDA helper defaults to `CUDA_ARCHITECTURES=121` when no architecture
is supplied, matching GB10/Spark. Override it explicitly for other GPUs.

On macOS the same target builds against the CUDA-disabled stub and exits with
`CUDA disabled`.

## Run

Small smoke:

```bash
./build-cuda/ds4_expert_queue_dummy --json --tokens 8 --topk 6 --experts 32 --hidden 64 --mid 128 --out 64 --iterations 2
```

Sorted expert-queue smoke:

```bash
./build-cuda/ds4_expert_queue_dummy --json --sorted --tokens 8 --topk 6 --experts 32 --hidden 64 --mid 128 --out 64 --iterations 2
```

Deeper synthetic queue smoke:

```bash
./build-cuda/ds4_expert_queue_dummy --json --sorted --tokens 128 --topk 6 --experts 256 --route-experts 64 --hidden 128 --mid 256 --out 128 --iterations 4
```

Throughput-oriented shape:

```bash
./build-cuda/ds4_expert_queue_dummy --json --tokens 128 --topk 6 --experts 256 --hidden 128 --mid 256 --out 128 --iterations 8
```

Larger synthetic batches should be swept separately for interactive and bulk
lanes. Start with `tokens=16,32,64,128,256,512` and keep dimensions fixed so
the scaling curve is attributable to queue depth rather than matrix size.

## Interpreting Output

Key fields:

- `gateup_ms`: routed gate/up synthetic time over all iterations.
- `down_ms`: routed down synthetic time over all iterations.
- `tokens_per_s`: aggregate synthetic decode rows per second.
- `expert_pairs_per_s`: `tokens * topk` expert assignments per second.
- `estimated_gib_per_s`: rough read movement rate for the synthetic kernels.
- `active_experts`, `max_queue_depth`, and `mean_queue_depth`: host-built
  route queue statistics. In `--sorted` mode these queues drive the CUDA grid.
- `route_experts`: optional synthetic route cap. Set this below `experts` to
  create deeper per-expert queues without changing the allocated model shape.

The acceptance gate is not a specific number yet. The first proof question is
whether `tokens_per_s` scales upward as batch size grows while per-token time
falls. If this dummy path scales but real decode does not, the remaining
bottleneck is attention/KV/session orchestration rather than expert math.

## Sorted Mode

`--sorted` builds a host-side queue layout that mirrors the real expert-routing
shape:

```text
selected pair ids -> expert_counts + expert_offsets + sorted_pairs
```

The CUDA gate/up kernel launches by `(row_block, expert, queue_slot)` and reads
`sorted_pairs[expert_offsets[expert] + queue_slot]`. The down kernel uses the
same expert queue and atomically accumulates each expert contribution into the
token output row.

`--route-experts N` constrains synthetic selected experts to `[0,N)`. This is
useful for stressing queue depth; for example, `tokens=128 topk=6
route_experts=64` gives an average active depth near `12` instead of `3`.

This is still a synthetic float benchmark, but it now exercises the core queue
plumbing that the real DS4 decode scheduler needs: selected rows are grouped by
expert, queue depths are visible, and the kernels consume the queued layout
instead of a flat unsorted pair list.

## Spark0 Smoke Result

On Spark0 with CUDA 13, the target builds and runs with:

```bash
./build-cuda-dummy/ds4_expert_queue_dummy --json --tokens 64 --topk 6 --experts 256 --hidden 128 --mid 256 --out 128 --iterations 4
```

Observed on the first pass:

- `tokens_per_s`: about `60k` synthetic rows/s.
- `expert_pairs_per_s`: about `360k` routed expert pairs/s.
- `estimated_gib_per_s`: about `178 GiB/s`.

After adding sorted expert queues, a route-capped synthetic run on Spark0:

```bash
./build-cuda-sorted-dummy/ds4_expert_queue_dummy --json --sorted \
  --tokens 2048 --topk 6 --experts 256 --route-experts 64 \
  --hidden 128 --mid 256 --out 128 --iterations 2
```

reported:

- `active_experts`: `64`
- `mean_queue_depth`: `192`
- `tokens_per_s`: about `193k` synthetic rows/s
- `expert_pairs_per_s`: about `1.16M` routed expert pairs/s
- `estimated_gib_per_s`: about `564 GiB/s`

This route-capped result is not a model-quality claim. It proves the queue
layout and kernel launch shape can consume deep per-expert queues at much higher
synthetic throughput than the shallow uniform route case.

This is a deliberately naive float kernel, so it is not a ceiling for the real
quantized MoE kernels. It is a baseline that proves the benchmark path compiles,
runs, and can now be optimized independently.

## Real DS4 Bridge

The first real-runtime bridge is:

```text
docs/antirez-patches/ds4-3630e64-cuda-moe-batched-expert-slice-queue.patch
```

Apply it after the existing MTP/Q4K, multi-model cache, and one-token expert
slice-cache patches. It adds `DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1`, which
uses the real batched selected-expert tensor to build sorted expert counts,
copies only the 256-count histogram back to host, caches active gate/up/down
expert slices, and launches sorted MoE kernels through per-expert pointer
tables.

This is no longer synthetic routing: the active experts come from the model's
real router output for the current batch.

The follow-on real-runtime bridge is:

```text
docs/antirez-patches/ds4-3630e64-cuda-moe-batched-expert-tile-slices.patch
```

Apply it after the batched expert-slice queue patch. It keeps expert-tile
kernels enabled with `DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1` and passes
optional gate/up/down per-expert slice pointer tables into the row32, row-span,
and block16 tiled kernels. This is the first version where the real active
expert cache and the high-throughput tile route are wired together; the next
measurement target is comparing it against full-slab tiles under
`DS4_CUDA_MOE_PROFILE=1`.

## Spark0 Real-Kernel Smoke

On Spark0, the full patch chain through
`ds4-3630e64-cuda-moe-batched-expert-tile-slices.patch` builds with:

```bash
make -C /tmp/ds4-tile-slices-compile CUDA_ARCH=sm_121 ds4_cuda.o
make -C /tmp/ds4-tile-slices-compile CUDA_ARCH=sm_121 ds4 ds4-bench
```

A tiny `ds4-bench` graph smoke emitted MoE profile lines, but it later failed
inside the compressed-attention/KV path. Treat that old `ds4-bench` signal as a
path smoke only. It is not a correctness benchmark for the MoE queue.

While wiring the tiled active-slice path, a targeted probe caught a real bug:
the slice pointer table was allocated through the same global CUDA temp buffer
as the sorted-pair scratch. Because `cuda_tmp_alloc(...)` reuses the existing
allocation when the new request is smaller, the pointer table overwrote expert
counts/offsets. That produced very fast but non-finite output. The tile-slice
patch now reserves pointer-table bytes inside the sorted scratch allocation and
passes that region to `cuda_moe_prepare_counted_expert_slices(...)`.

## Targeted Real-Kernel Probe

The follow-on patch:

```text
docs/antirez-patches/ds4-3630e64-cuda-moe-probe-and-startup-cache-skip.patch
```

adds a focused upstream `ds4` mode:

```bash
DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \
DS4_CUDA_WEIGHT_CACHE_LIMIT_GB=4 \
DS4_CUDA_WEIGHT_ARENA_CHUNK_MB=256 \
DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \
DS4_CUDA_MOE_PROBE_COMPARE_FULL=1 \
./ds4 -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  --cuda --cuda-moe-probe --cuda-moe-layer 1 --cuda-moe-tokens 16 --cuda-moe-iters 3
```

This probe runs the real router matmul, real batched router selection, and real
`ds4_gpu_routed_moe_batch_tensor(...)` against actual model expert weights. It
then optionally reruns the full-slab tiled path in the same process and reports
output diff statistics.

The full-slab compare is intentionally heavier: with startup caching skipped it
may need to cold-load hundreds of MiB of contiguous MoE slabs. If that path hits
a CUDA upload timeout, rerun without `DS4_CUDA_MOE_PROBE_COMPARE_FULL=1` for the
active-slice timing, or warm/cache the full-slab path before comparing.

Spark0 result after fixing the scratch collision:

```json
{"cuda_moe_probe":true,"layer":1,"tokens":16,"pairs":96,"iterations":3,"active_experts":80,"mean_queue_depth":1.200,"max_queue_depth":3,"avg_ms":200.661,"best_ms":5.710,"best_pairs_per_s":16811.976,"out_fnv64":"5c70e771dfb07f19","out_nonfinite":0,"full_slab_fnv64":"5c70e771dfb07f19","full_slab_nonfinite":0,"full_slab_max_abs_diff":0,"full_slab_mean_abs_diff":0}
```

Larger batch sweeps on Spark0 with finite outputs:

| tokens | pairs | active experts | mean queue | max queue | best ms | pairs/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 128 | 768 | 242 | 3.174 | 10 | 20.462 | 37.5k |
| 256 | 1536 | 256 | 6.000 | 13 | 26.960 | 57.0k |
| 512 | 3072 | 256 | 12.000 | 23 | 43.097 | 71.3k |
| 1024 | 6144 | 256 | 24.000 | 43 | 82.166 | 74.8k |

The important correction: the previously observed `31x` number was not a valid
speedup; it came from the scratch overwrite causing incomplete/corrupt work.
The honest current result is correctness parity with full-slab tiled kernels
and improving expert-pair throughput as queue depth grows. The next CUDA work
needs to reduce the real gate/up and down tile compute time, not just change
which weight ranges are resident.

## Spark0 Down-Tile Retune

The first real tuning win is disabling the block16 down tile kernel as the
default for batched expert tiles. On Spark/GB10, the non-block16 tile16 down
kernel is consistently faster at useful batch sizes, while preserving finite
output. The patch keeps `DS4_CUDA_MOE_DOWN_BLOCK16=1` as an explicit A/B escape
hatch.

Spark0 before/after, same layer-1 probe and model:

| tokens | old best ms | new best ms | speedup | new pairs/s |
| ---: | ---: | ---: | ---: | ---: |
| 256 | 26.960 | 15.346 | 1.76x | 100.1k |
| 512 | 43.097 | 21.389 | 2.02x | 143.6k |
| 1024 | 82.166 | 38.461 | 2.14x | 159.7k |

The `tokens=1024` MoE-only, one-layer rate is now about `26.6k token-layer/s`.
With 43 DS4 layers, that is a rough `620 tok/s` aggregate MoE-only ceiling
before attention, shared experts, KV, sampling, and scheduling overhead. This is
still not end-to-end decode throughput, but it is a real improvement in the
routed expert kernel path.
