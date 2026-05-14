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

A tiny direct-model `ds4-bench` prefill smoke currently exits after emitting
layer profiles, so this is a kernel-path/profile smoke rather than a completed
generation benchmark. With `tokens=2, pairs=12`, warm-layer MoE profile lines
on the same prompt/model showed:

- batched expert slices + expert tiles: `total=0.236 ms`, with
  `gateup=0.036 ms` and `down=0.117 ms`
- batched expert slices with `DS4_CUDA_MOE_NO_EXPERT_TILES=1`:
  `total=7.430 ms`, with `gateup=5.753 ms` and `down=1.622 ms`
- default full-slab path: `total=262.553 ms`, with `gateup=167.604 ms` and
  `down=94.888 ms`

That makes the tiled active-expert slice route roughly `31x` faster than the
non-tiled active-expert slice fallback for this tiny layer smoke. It should not
be treated as final tok/sec, but it is the first measured signal that the real
expert queue is landing on the intended high-throughput CUDA path.
