# DS4 dual all-Spark pipeline API

This topology replaces the static `5x Qwen + 2x DSV4 + 1x experiment` split with two resident pipeline services over the same Spark fleet:

- `qwen27_bf16_pp8`, `Qwen/Qwen3.6-27B`, BF16, text-only, 64 layers, default PP8 partition `9,9,9,8,8,8,8,5`, API on spark0 port `8101`, max model length `262144`, production caps `max_num_seqs=12`, `max_num_batched_tokens=65536`, `gpu_memory_utilization=0.35`.
- `dsv4_flash_pp8`, `deepseek-ai/DeepSeek-V4-Flash`, existing mixed FP4/FP8 + SimpleCPUOffload path, 43 layers, default PP8 partition `6,6,6,5,5,5,5,5`, API on spark0 port `8102`, max model length `262144`, production caps `max_num_seqs=8`, `max_num_batched_tokens=32768`, `gpu_memory_utilization=0.30`.

`spark0` is the queue and API ingress. Model requests bind to `spark0` but carry the full pipeline `selected_node_ids`. Both services share compute domain `spark-fleet-0`; DS4 owns the queue lease and batch admission above the two vLLM servers.

## Node prerequisites

Install these on every Spark participating in either pipeline:

```bash
sudo apt-get install -y gcc g++ python3.12-dev
/home/$USER/ds4-vllm-local/bin/python -m pip install pytest
```

`python3.12-dev` is required even when vLLM is already installed, because Triton JIT compiles small launcher modules during startup and needs `Python.h`.
`pytest` is required by the current CuPy/Torch runtime inspection path during profile/warmup; without it, non-head pipeline ranks can fail while registering custom ops.

If sudo is unavailable, extract `libpython3.12-dev` under `$HOME/ds4_deps/python3.12-dev`; the launchers will add both `$HOME/ds4_deps/python3.12-dev/usr/include/python3.12` and `$HOME/ds4_deps/python3.12-dev/usr/include` to `CPATH`. Override the Python include directory with `DS4_PYTHON_INCLUDE_DIR` when needed.

## Launch model services

Run one rank per Spark. For Qwen:

```bash
cd /home/$USER/ds4_on_spark/v2
export DS4_SPARK_ETH_IF=enP7s7
export HEAD_ADDR=10.20.0.10
export NNODES=8
export MASTER_PORT=29527
export API_PORT=8101
for rank in 0 1 2 3 4 5 6 7; do
    ssh spark${rank} "cd /home/\$USER/ds4_on_spark/v2 && NODE_RANK=${rank} HEAD_ADDR=${HEAD_ADDR} NNODES=${NNODES} MASTER_PORT=${MASTER_PORT} API_PORT=${API_PORT} ./scripts/ds4_launch_qwen27_bf16_pp.sh"
done
```

For DSV4:

```bash
cd /home/$USER/ds4_on_spark/v2
export DS4_SPARK_ETH_IF=enP7s7
export HEAD_ADDR=10.20.0.10
export NNODES=8
export MASTER_PORT=29544
export API_PORT=8102
for rank in 0 1 2 3 4 5 6 7; do
    ssh spark${rank} "cd /home/\$USER/ds4_on_spark/v2 && NODE_RANK=${rank} HEAD_ADDR=${HEAD_ADDR} NNODES=${NNODES} MASTER_PORT=${MASTER_PORT} API_PORT=${API_PORT} ./scripts/ds4_launch_dsv4_flash_pp.sh"
done
```

For `N=1`, the launchers use a single full-layer stage. For `N=8`, they use the tuned production partitions above. For any other `N`, the launchers default to a simple `layers / N` allocator, distributing the remainder to the earliest stages. Recipes may override with `QWEN27_PP_LAYER_PARTITION` or `DSV4_FLASH_PP_LAYER_PARTITION`; the partition must sum to 64 for Qwen27 and 43 for DSV4 Flash.

`HEAD_ADDR` must be the spark0 address on `DS4_SPARK_ETH_IF`. The launchers pin `NCCL_SOCKET_IFNAME`, `GLOO_SOCKET_IFNAME`, and `TP_SOCKET_IFNAME` to that interface and publish the local interface address as `VLLM_HOST_IP`; using the Wi-Fi hostname can make Gloo advertise `127.0.0.1` and fail multi-node startup.

The queue topology follows the same rule: omit `layer_partition`, set it to `even` / `auto` / `layers/n`, or provide `layer_partition_by_node` for arbitrary per-node layer counts. Overrides are validated against `total_layers` before the topology loads.

Qwen keeps the 262k model limit and 12 concurrent request slots, but its default GPU memory utilization is intentionally capped at `0.35` for dual-resident service. That sizes the resident KV pool for normal mixed traffic, roughly twelve sub-100k contexts with margin, instead of reserving enough GPU memory for twelve simultaneous full-262k contexts. Its default scheduler chunk is `65536` tokens so long-prefix prefills do not get chopped into tiny 2k/4k steps. Raise `QWEN27_GPU_MEMORY_UTILIZATION` only for Qwen-only qualification runs.

DSV4 no longer carries the old 2-node safety cap of one sequence. The dual-resident default is `max_num_seqs=8`, `max_num_batched_tokens=8192`, and `gpu_memory_utilization=0.30`, with DS4 queue admission allowing a 32-request service window while vLLM keeps eight scheduled sequences. The `0.30` GPU cap is deliberate: with Qwen resident at roughly 33-36 GiB on 120 GiB Sparks, DSV4 gets a bounded resident pool while the pair keeps roughly 10-20 GiB free instead of letting the two vLLM servers over-reserve the card. Use `DSV4_SAFE_MODE=1` or explicit `DSV4_MAX_NUM_SEQS=1 DSV4_MAX_NUM_BATCHED_TOKENS=2048 DSV4_GPU_MEMORY_UTILIZATION=0.68` only when isolating DSV4 by itself. For DSV4-only benchmarking, raise `DSV4_GPU_MEMORY_UTILIZATION` and use the TP2 native benchmark launcher below.

## Native GB10 FP4 Policy

DS4 production must not silently fall back to Marlin, CPU, or emulation kernels on GB10. Marlin references can still exist in upstream vLLM because vLLM supports many GPUs and checkpoint shapes, but the DS4 launch path pins native Blackwell kernels and enables strict rejection:

```text
VLLM_DS4_STRICT_NATIVE_FP4=1
VLLM_DISABLED_KERNELS=MarlinNvFp4LinearKernel,EmulationNvFp4LinearKernel,MarlinMxFp4LinearKernel,MarlinMxfp8LinearKernel,EmulationMxfp8LinearKernel,MarlinFP8ScaledMMLinearKernel
VLLM_MXFP4_USE_MARLIN=0
VLLM_TEST_FORCE_FP8_MARLIN=0
```

The DSV4 Flash PP service requires the native backend recipe:

```text
--linear-backend deep_gemm
--moe-backend deep_gemm
--compilation-config '{"cudagraph_mode":"FULL_AND_PIECEWISE","custom_ops":["all"]}'
```

Use `v2/scripts/ds4_launch_dsv4_flash_tp2_native_benchmark.sh` when validating the dual-Spark native fast path against external TP=2 benchmark numbers. Do not compare PP8 single-stream latency directly to TP2 single-stream latency: TP2 is a latency profile, while PP8 is for aggregate fleet utilization and pipeline-layer KV sharding.

## Optional Qwen27 NVFP4/MTP Lane

The primary Qwen service remains BF16 PP pipeline for quality acceptance. The optional NVFP4/MTP launcher is a separate throughput lane:

```bash
QWEN27_NVFP4_MTP_MODEL=/home/$USER/models/hf/sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP \
  ./v2/scripts/ds4_launch_qwen27_nvfp4_mtp_native.sh
```

Do not replace BF16 until local eval accepts the NVFP4/MTP model. The throughput lane uses text-only ModelOpt NVFP4, native FlashInfer/CUTLASS, FP8 KV, and Qwen MTP.

## Start the spark0 coordinator

```bash
cd /home/$USER/ds4_on_spark/v2
DS4_NVME_ROOT=/home/$USER/ds4_nvme ./scripts/ds4_coordinator_api.sh
```

Equivalent direct command:

```bash
cd /home/$USER/ds4_on_spark/v2
export PYTHONPATH=$PWD/src
python3 -m ds4_infer.api \
    --host 0.0.0.0 \
    --port 8700 \
    --queue-dir /home/$USER/ds4_nvme/ds4_queue \
    --profiles-dir profiles/models \
    --topology profiles/topology/static_sparks.json
```

The coordinator can run work inline for synchronous API requests. A separate spark0 worker is still useful for async queue traffic:

```bash
cd /home/$USER/ds4_on_spark/v2
DS4_NVME_ROOT=/home/$USER/ds4_nvme ./scripts/ds4_pipeline_queue_worker.sh
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
    "model":"qwen27_bf16_pp8",
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
    "service_id":"qwen27_bf16_pp8",
    "total_bytes":8000000000,
    "total_tokens":131072,
    "owner":"world-model",
    "storage_root":"/home/$USER/ds4_nvme/ds4_kv_external",
    "metadata":{"kind":"event-prefix","tags":["wm","events"]}
  }'
```

For Qwen27 PP8, that logical 8 GB object becomes eight ~1 GB stage shards:

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
    "service_id":"qwen27_bf16_pp8",
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
    "service_id":"qwen27_bf16_pp8",
    "node_id":"spark3",
    "state":"prod",
    "metrics":{"decode_tok_s":123.0,"kv_shard_bytes":0}
  }'
```

The status endpoint combines topology, queue leases, telemetry, and per-node KV shard accounting:

```bash
curl -s http://spark0:8700/ds4/pipelines
```
