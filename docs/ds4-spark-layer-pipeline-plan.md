# DS4 Spark Layer Pipeline Plan

Layer sharding is now a first-class distributed experiment for DS4 on multiple
Sparks. The design is contiguous layer-stage pipeline parallelism, not
cross-Spark expert sharding and not round-robin per-layer placement.

Primary target:

```text
coordinator -> stage 0 -> stage 1 -> ... -> stage N-1 -> coordinator
```

Each stage owns a contiguous layer range. For three Sparks an initial placement
can be:

```text
stage 0: embedding + layers 0..14
stage 1: layers 15..28
stage 2: layers 29..42 + final norm/head/sampler
```

The exact split must be timing-driven. DS4 Flash has a 43-layer all-MoE backbone
with 256 routed experts, one shared expert per block, and top-6 routing. The
pipeline must therefore keep each stage's local expert queues and treat
cross-stage traffic as activation transfer between contiguous layer blocks.

## Throughput Model

Layer pipelining targets steady-state throughput, not single-request latency:

```text
single_spark_time_per_microbatch = T0 + T1 + ... + Tn
pipeline_stage_interval = max(stage_i_compute_ms + stage_i_transfer_ms)
steady_state_speedup ~= single_spark_time_per_microbatch / pipeline_stage_interval
```

For `M` microbatches:

```text
pipeline_wall_ms = sum(stage_intervals) + ((M - 1) * max(stage_intervals))
serial_wall_ms = M * single_spark_time_per_microbatch
speedup = serial_wall_ms / pipeline_wall_ms
```

This makes pipeline bubbles and stage imbalance visible. A three-stage balanced
pipeline approaches `3x` only when enough microbatches are in flight and
activation transfer is small relative to stage compute.

## Runtime Ownership

Coordinator owns:

- request admission;
- prefix/model/runtime grouping;
- microbatch formation;
- stage schedule and backpressure;
- cancellation and release;
- final token collection.

Stage 0 owns:

- token embedding;
- early contiguous layer weights;
- early-layer KV;
- local expert queues for early layers.

Middle stages own:

- middle contiguous layer weights;
- stage-local KV;
- local expert queues for their layer range.

Final stage owns:

- late contiguous layer weights;
- late-layer KV;
- final norm/head/sampler;
- token outputs.

## Activation Message V1

Stage messages use a JSON metadata header plus a binary tensor payload. The
activation payload must never be JSON-serialized.

```json
{
  "format": "ds4-layer-pipeline-activation-v1",
  "pipeline_id": "spark-ring-ds4-flash",
  "model_id": "deepseek-v4-flash",
  "runtime_id": "llama.cpp-kamnxt-or-ds4-native",
  "microbatch_id": "mb_000123",
  "decode_step": 17,
  "from_stage": 0,
  "to_stage": 1,
  "session_ids": ["s0", "s1", "s2"],
  "positions": [2048, 2048, 2048],
  "batch_size": 3,
  "dtype": "fp16",
  "layout": "ds4-stage-boundary-v1",
  "boundary_after_layer": 14,
  "tensor_shape": ["unknown-until-probed"],
  "tensor_ref": {
    "transport": "tcp_binary",
    "byte_count": 0,
    "sha256": "..."
  }
}
```

`tensor_shape` is intentionally not finalized. DS4 Flash uses Hyper-Connections
with `hc_mult=4`, so the first implementation probe must inspect the actual
forward state that crosses a block boundary before any C/CUDA ABI is frozen.

## Distributed Prefix Handle V1

KV must stay stage-local. Decode steps send activations forward; they do not
move KV between Sparks.

```json
{
  "format": "ds4-distributed-prefix-handle-v1",
  "prefix_cache_key": "...",
  "pipeline_id": "spark-ring-ds4-flash",
  "model_id": "deepseek-v4-flash",
  "tokenizer_sha256": "...",
  "stage_handles": [
    {
      "stage": 0,
      "node_id": "spark0",
      "layer_range": [0, 14],
      "kv_handle": "..."
    },
    {
      "stage": 1,
      "node_id": "spark1",
      "layer_range": [15, 28],
      "kv_handle": "..."
    },
    {
      "stage": 2,
      "node_id": "spark2",
      "layer_range": [29, 42],
      "kv_handle": "..."
    }
  ]
}
```

The Spark names above are examples. The implementation must be driven by a
manifest with generic `stage_count`, `stage_id`, `node_id`, and `layer_range`
fields. No code should assume three or eight Sparks.

## Prefill And Decode

Prefill sends sequence chunks:

```text
[batch * chunk_tokens, boundary_state]
```

Decode sends one activation row per active session:

```text
[batch_sessions, boundary_state]
```

Prefill can use chunked pipeline fill/drain. Decode needs continuous batching:
while one microbatch is on the final stage, another should be on the middle
stage and another on the first stage. The final stage samples tokens and returns
token IDs to the coordinator, which admits those sessions into the next decode
microbatch.

## Measurement Gates

1. Use `scripts/ds4_layer_pipeline_sim.py` to model bubble cost, stage balance,
   and activation transfer overhead for `N=1,2,3` and microbatch counts
   `M=1,2,4,8,16,32`.
2. Use `scripts/spark_activation_transfer_bench.py` to measure binary
   activation-sized transfers across Spark links. Sweep batch sizes
   `32,64,128,256,512,1024`.
3. Build a dummy stage pipeline that validates ordering, checksums,
   backpressure, cancellation, and per-stage timing without DS4 weights.
4. Probe the true DS4 stage-boundary tensor shape with `hc_mult=4`.
5. Implement a tiny deterministic PP=1 versus PP=N correctness gate:
   logits/tokens must match within the chosen quantized-runtime tolerance.
6. Only after the correctness gate passes, report end-to-end tok/sec for
   prefill and decode separately.

## First Acceptance Criteria

- No hardcoded Spark count.
- No round-robin layer placement across nodes.
- No cross-Spark expert sharding in this stage of the project.
- KV stays stage-local.
- Local expert queues remain inside each stage.
- Every throughput claim includes bubble, transfer, and bottleneck-stage
  accounting.
- Prefill and decode measurements are reported separately.
- Centaur sees only provider telemetry and does not import DS4 CUDA details.

## References

- PyTorch pipeline parallelism documentation:
  <https://docs.pytorch.org/docs/2.12/distributed.pipelining.html>
- NVIDIA NeMo-AutoModel DS4 Flash documentation:
  <https://docs.nvidia.com/nemo/automodel/nightly/guides/llm/dsv4-flash.html>
