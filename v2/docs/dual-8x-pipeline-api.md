# DS4 three-pipeline all-Spark API

This topology replaces the static `5x Qwen + 2x DSV4 + 1x experiment` split with three resident pipeline services over the same Spark fleet:

- `qwen27_nvfp4_pp8`, `sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP`, ModelOpt NVFP4, text-only, MTP disabled by default, 64 layers, default PP8 partition `9,9,9,8,8,8,8,5`, API on spark0 port `8103`.
- `qwen27_bf16_pp8`, `Qwen/Qwen3.6-27B`, BF16, text-only, 64 layers, default PP8 partition `9,9,9,8,8,8,8,5`, API on spark0 port `8101`.
- `dsv4_flash_pp8`, `deepseek-ai/DeepSeek-V4-Flash`, existing mixed FP4/FP8 + SimpleCPUOffload path, 43 layers, default PP8 partition `6,6,6,5,5,5,5,5`, API on spark0 port `8102`.

`spark0` is the queue and API ingress. Model requests bind to `spark0` but carry the full pipeline `selected_node_ids`. All three services share compute domain `spark-fleet-0`; DS4 owns the queue lease and batch admission above the vLLM servers.

## Launch model services

Run one rank per Spark. For Qwen NVFP4 cache-primary PP:

```bash
cd /home/$USER/ds4_on_spark/v2
export HEAD_ADDR=spark0
export NNODES=8
export MASTER_PORT=29537
export API_PORT=8103
for rank in 0 1 2 3 4 5 6 7; do
    ssh spark${rank} "cd /home/\$USER/ds4_on_spark/v2 && NODE_RANK=${rank} HEAD_ADDR=${HEAD_ADDR} NNODES=${NNODES} MASTER_PORT=${MASTER_PORT} API_PORT=${API_PORT} ./scripts/ds4_launch_qwen27_nvfp4_pp.sh"
done
```

The Qwen PP service is cache-primary. It uses one stage per Spark so external KV/state is sharded by layer ownership. The checkpoint contains MTP weights, but MTP is intentionally off by default until PP speculative-cache commit semantics are verified.

For DSV4:

```bash
cd /home/$USER/ds4_on_spark/v2
export HEAD_ADDR=spark0
export NNODES=8
export MASTER_PORT=29544
export API_PORT=8102
for rank in 0 1 2 3 4 5 6 7; do
    ssh spark${rank} "cd /home/\$USER/ds4_on_spark/v2 && NODE_RANK=${rank} HEAD_ADDR=${HEAD_ADDR} NNODES=${NNODES} MASTER_PORT=${MASTER_PORT} API_PORT=${API_PORT} ./scripts/ds4_launch_dsv4_flash_pp.sh"
done
```

For `N=1`, the launchers use a single full-layer stage. For `N=8`, they use the tuned production partitions above. For any other `N`, the launchers default to a simple `layers / N` allocator, distributing the remainder to the earliest stages. Recipes may override with `QWEN27_PP_LAYER_PARTITION` or `DSV4_FLASH_PP_LAYER_PARTITION`; the partition must sum to 64 for Qwen27 and 43 for DSV4 Flash.

The queue topology follows the same rule: omit `layer_partition`, set it to `even` / `auto` / `layers/n`, or provide `layer_partition_by_node` for arbitrary per-node layer counts. Overrides are validated against `total_layers` before the topology loads.

## Start the spark0 coordinator

```bash
cd /home/$USER/ds4_on_spark/v2
QUEUE_DIR=/home/$USER/ds4_queue ./scripts/ds4_coordinator_api.sh
```

Equivalent direct command:

```bash
cd /home/$USER/ds4_on_spark/v2
export PYTHONPATH=$PWD/src
python3 -m ds4_infer.api \
    --host 0.0.0.0 \
    --port 8700 \
    --queue-dir /home/$USER/ds4_queue \
    --profiles-dir profiles/models \
    --topology profiles/topology/static_sparks.json
```

The coordinator can run work inline for synchronous API requests. A separate spark0 worker is still useful for async queue traffic:

```bash
cd /home/$USER/ds4_on_spark/v2
QUEUE_DIR=/home/$USER/ds4_queue ./scripts/ds4_pipeline_queue_worker.sh
```

## Public API shape

The spark0 coordinator exposes compatibility endpoints instead of a DS4-only inference API:

```text
GET  /v1/models
POST /v1/chat/completions
POST /v1/completions
POST /v1/messages
```

`/v1/chat/completions` and `/v1/completions` accept the usual OpenAI-style `model`, `messages` or `prompt`, `temperature`, `max_tokens` / `max_completion_tokens`, and `response_format` fields. `/v1/messages` accepts Anthropic-style `model`, `system`, `messages`, `tools`, `metadata`, and `max_tokens` fields. All three paths also accept DS4 extensions: `ds4_async`, `batch_id`, `priority`, `ds4_job_class`, `ds4_capability`, and `external_kv` / `kv_cache`.

Streaming is rejected for now rather than silently downgraded. Async calls return a DS4 queue handle and can be collected through `/ds4/queue/collect`.

OpenAI-style example:

```bash
curl -s http://spark0:8700/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{
    "model":"qwen27_nvfp4_pp8",
    "messages":[{"role":"user","content":"extract events"}],
    "max_tokens":512,
    "metadata":{"job_class":"analysis"},
    "external_kv":{"namespace":"centaur.longmem","kv_key":"wm:event-prefix:42"}
  }'
```

Anthropic-style example:

```bash
curl -s http://spark0:8700/v1/messages \
  -H 'content-type: application/json' \
  -d '{
    "model":"deepseek-ai/DeepSeek-V4-Flash",
    "system":"You are the DS4 planner.",
    "messages":[{"role":"user","content":"plan the atom split"}],
    "max_tokens":1024,
    "metadata":{"job_class":"tool_chat"}
  }'
```

## Queue scheduling

The coordinator is the only process that chooses work. It applies:

- priority ordering and batch linger;
- one shared compute-domain lease for `spark-fleet-0`;
- service-level batch caps from topology, so DSV4 does not accidentally claim Qwen-sized batches;
- WAL-backed SQLite queue state with bounded busy waits and batched ready-prefill scans.

The worker path is still a single spark0 process. vLLM instances do not coordinate batch admission with each other; they receive already-admitted batches from DS4.

## External KV/cache API

External KV memory has a control-plane manifest and one shard row per pipeline stage. The current implementation does not pretend to perform GPU JIT page-in. `prefetch` marks intent and state; the vLLM connector must still perform the physical load when that path is wired.

Control endpoints:

```text
GET/POST /ds4/kvcache/lookup       manifest for one key
GET/POST /ds4/kvcache/list         namespace/prefix/owner/state listing
POST     /ds4/kvcache/declare      create or replace logical object + shards
POST     /ds4/kvcache/lease        read/write/prefetch/pin lease
POST     /ds4/kvcache/release      release lease
POST     /ds4/kvcache/prefetch     control-plane prefetch request
POST     /ds4/kvcache/commit       mark object/shards ready or update shard storage_uri/gpu state
POST     /ds4/kvcache/transition   state transition with metadata merge
POST     /ds4/kvcache/touch        update last-used, owner, priority, TTL, metadata
POST     /ds4/kvcache/pin          increment pin count
POST     /ds4/kvcache/unpin        decrement pin count
POST     /ds4/kvcache/evict        evict when not pinned
```

Declare a longmem prefix object:

```bash
curl -s http://spark0:8700/ds4/kvcache/declare \
  -H 'content-type: application/json' \
  -d '{
    "namespace":"centaur.longmem",
    "kv_key":"wm:event-prefix:42",
    "service_id":"qwen27_nvfp4_pp8",
    "total_bytes":8000000000,
    "total_tokens":131072,
    "owner":"world-model",
    "storage_root":"/home/$USER/ds4_kv_external",
    "metadata":{"kind":"event-prefix","tags":["wm","events"]}
  }'
```

For Qwen27 NVFP4 PP8, that logical 8 GB object becomes eight ~1 GB stage shards:

```text
spark0 layers 0:9
spark1 layers 9:18
spark2 layers 18:27
spark3 layers 27:35
spark4 layers 35:43
spark5 layers 43:51
spark6 layers 51:59
spark7 layers 59:64
```

Commit after the physical cache writer has materialized shard files:

```bash
curl -s http://spark0:8700/ds4/kvcache/commit \
  -H 'content-type: application/json' \
  -d '{
    "namespace":"centaur.longmem",
    "kv_key":"wm:event-prefix:42",
    "service_id":"qwen27_nvfp4_pp8",
    "object_state":"available",
    "shard_state":"ready_on_ssd"
  }'
```

Centaur tools should pass `external_kv` in model requests by namespace/key/service. The manifest is sufficient for longmem, diamondization, and compiler flows to pin, discover, lease, update metadata, and attach external memory without requiring full KV replication on every Spark.

## Telemetry

Each vLLM rank can report shorthand stage telemetry; the coordinator fills layer ownership from topology:

```bash
curl -s http://spark0:8700/ds4/pipeline/telemetry \
  -H 'content-type: application/json' \
  -d '{
    "service_id":"qwen27_nvfp4_pp8",
    "node_id":"spark3",
    "state":"prod",
    "metrics":{"decode_tok_s":123.0,"kv_shard_bytes":0}
  }'
```

The status endpoint combines topology, queue leases, telemetry, and per-node KV shard accounting:

```bash
curl -s http://spark0:8700/ds4/pipelines
```

## Native GB10 FP4 policy

The DS4 production profile must not silently fall back to Marlin, CPU, or emulation kernels on GB10. Marlin references may still exist inside upstream vLLM because vLLM supports many GPUs/checkpoint shapes, but the DS4 launch path pins native Blackwell kernels and enables strict rejection:

```text
VLLM_DS4_STRICT_NATIVE_FP4=1
VLLM_DISABLED_KERNELS=MarlinNvFp4LinearKernel,EmulationNvFp4LinearKernel,MarlinMxFp4LinearKernel,MarlinMxfp8LinearKernel,EmulationMxfp8LinearKernel,MarlinFP8ScaledMMLinearKernel
VLLM_MXFP4_USE_MARLIN=0
VLLM_TEST_FORCE_FP8_MARLIN=0
```

For DSV4 Flash native paths, do not force DeepGEMM on SM12x unless an explicitly validated DeepGEMM wheel supports the required FP8×FP4 kernels. The DSV4 launchers default to native `auto` routing and fail closed if native CUTLASS/FlashInfer routes are unavailable.

FlashInfer autotune is disabled for service startup by default. It can benchmark large dummy forwards at `max_num_batched_tokens`, which is useful only for dedicated tuning and dangerous during bringup on UMA nodes:

```text
DS4_ENABLE_FLASHINFER_AUTOTUNE=0
```

Only set `DS4_ENABLE_FLASHINFER_AUTOTUNE=1` in an explicit tune/bench run, not in resident production launchers.

The old DSV4 single-request safety cap has been removed for PP8. The default is now:

```text
vLLM max_num_seqs:          8
vLLM max_num_batched_tokens: 8192
DS4 queue_concurrency:      32
DS4 refill_low_watermark:   24
```

Use `v2/scripts/ds4_launch_dsv4_flash_tp2_native_benchmark.sh` when validating the dual-Spark native fast path against external TP=2 benchmark numbers. Do not use the PP8 service for that specific comparison: TP2 measures single-request latency across two Sparks; PP8 is for aggregate fleet utilization and KV-sharded operational behavior.

## Qwen MTP under PP

The Qwen NVFP4 checkpoint includes MTP weights, but the production PP service
does not enable speculative decoding by default. This is deliberate: the
external KV object must represent verified base-model state. Draft-only MTP
state must never be committed into Centaur longmem or diamondized cache objects.

For a targeted bring-up only:

```bash
export QWEN27_NVFP4_ENABLE_MTP=1
export QWEN27_NVFP4_ENABLE_MTP_EXPERIMENTAL=1
export QWEN27_SPECULATIVE_CONFIG='{"method":"qwen3_5_mtp","num_speculative_tokens":3}'
./v2/scripts/ds4_launch_qwen27_nvfp4_pp.sh
```

Do not promote that mode until accepted-token cache commits are proven against
the external KV API.
