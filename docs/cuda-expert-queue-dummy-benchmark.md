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
