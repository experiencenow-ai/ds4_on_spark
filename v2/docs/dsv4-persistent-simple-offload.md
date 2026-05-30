# DSV4 Persistent Native HMA Offload

DSV4 persistent KV is implemented on top of vLLM's native
`SimpleCPUOffloadConnector`. This is deliberately not an LMCache launch. The
live DSV4 path already stores the correct HMA KV block tensors in native CPU
offload; the DS4 patch makes that CPU offload pool durable across vLLM
restarts.

Current production target:

```text
launch script: scripts/ds4_dsv4_spark45_local_vllm.sh
systemd units: ds4-dsv4-local-worker.service, ds4-dsv4-local-head.service
vLLM fork:     https://github.com/experiencenow-ai/vllm
vLLM base:     c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34
```

The earlier Docker runtime mod remains in `runtime_mods/` as the historical
proof and rollback substrate. Do not use it to recreate the current
source-built local runtime.

## What Is Patched

The source-built fork carries the same SimpleCPUOffload persistence seams in
vLLM source. The legacy Spark Docker recipe wrapper can still install:

```text
v2/runtime_mods/dsv4_persistent_simple_offload
```

This was real vLLM code patching, packaged as a launch-time runtime mod so the
first proof run was easy to revert and did not permanently mutate the base
image. `run.sh` executes `patch_vllm.py` inside each DSV4 container. The patcher
copies `persistent_disk.py` into the installed vLLM package and edits these
vLLM files inside the temporary Docker container:

```text
vllm/v1/simple_kv_offload/metadata.py
vllm/v1/simple_kv_offload/manager.py
vllm/v1/simple_kv_offload/worker.py
```

It also copies:

```text
vllm/v1/simple_kv_offload/persistent_disk.py
```

The code changes are intentionally narrow:

```text
metadata.py:
  add load_block_hashes and store_block_hashes to SimpleCPUOffloadMetadata

manager.py:
  restore scheduler CPU-block hash index at startup
  persist scheduler block/hash assignments after stores complete
  advertise persistent external hits with one HMA-LCM guard block
  validate replay loads with one extra HMA-LCM lookahead block
  pass block hashes through load/store transfer metadata

worker.py:
  restore CPU offload tensors at startup
  fail closed if a requested load block was not restored
  persist CPU offload tensors after store DMA completion

persistent_disk.py:
  store scheduler_index.json
  store per-rank worker_index.json
  store one torch payload per CPU offload block under workers/<rank>/blocks/
```

The scheduler persists and restores the HMA CPU block hash index. Workers
persist and restore the actual CPU offload tensors for each block. Load metadata
includes the expected block hashes so a worker that failed to restore tensor
data fails visibly instead of loading empty CPU blocks into GPU cache.

DSV4's HMA grouped/sliding layout needs one aligned lookahead block when vLLM
validates the load after allocating GPU slots. The scheduler therefore logs the
raw persistent hit, advertises one HMA LCM less than that raw hit, and validates
the load with the extra lookahead hashes. Without that lookahead, the first
restart replay under-advertises by exactly one 256-token HMA unit during
post-allocation validation.

## Golden Recipe

Do not preserve DSV4 by launching a generic cache connector. Preserve these
invariants together:

```text
model:                         deepseek-ai/DeepSeek-V4-Flash
served model:                  deepseek-v4-flash
nodes:                         spark4 + spark5 as one no-Ray TP=2 service
historical proof vLLM ref:     dda4668b59567416f86956cfe7bbc1eab371a61e
current source vLLM ref:       c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34
runtime:                       ~/ds4-vllm-local-c6e55a8
max_model_len:                 262144
MTP speculative decoding:      enabled, deepseek_mtp with 2 speculative tokens
block_size:                    256
hybrid KV manager:             enabled
prefix caching:                enabled
KV cache dtype:                fp8
GPU memory utilization:        0.68
prefill chunk:                 max_num_batched_tokens=2048
max active sequences:          1
KV offload backend:            native
KV offload size:               2 GiB total default, 1 GiB per TP rank
KV connector:                  SimpleCPUOffloadConnector
persistent implementation:     source-built SimpleCPUOffload persistence
observability:                 KV cache metrics and iteration details enabled
PYTHONHASHSEED:                0
```

The key launch flags are:

```text
--max-model-len ${DS4_DSV4_MAX_MODEL_LEN:-262144}
--enable-prefix-caching
--no-disable-hybrid-kv-cache-manager
--kv-cache-dtype fp8
--gpu-memory-utilization ${DS4_DSV4_GPU_MEMORY_UTILIZATION:-0.68}
--max-num-seqs ${DS4_DSV4_MAX_NUM_SEQS:-1}
--max-num-batched-tokens ${DS4_DSV4_MAX_NUM_BATCHED_TOKENS:-2048}
--kv-offloading-size ${DS4_DSV4_KV_OFFLOAD_SIZE:-2}
--kv-offloading-backend native
--kv-cache-metrics
--enable-logging-iteration-details
--speculative-config '{"method":"deepseek_mtp","num_speculative_tokens":2}'
VLLM_USE_SIMPLE_KV_OFFLOAD=1
```

The host-local Spark4/5 runtime was requalified on May 27 2026 after SSH
recovery. With `gpu_memory_utilization=0.8` and `max_num_batched_tokens=8192`,
even a 3k-token proof-scale request hit NVIDIA driver `NV_ERR_NO_MEMORY`
during prefill/JIT before any persistent store files were written. The
host-local default was first lowered to `0.75` plus `4096`, but the first
32-line warm request still pushed spark5 to `4.4 GiB` swap and made spark4 stop
serving SSH banners. The next production target is therefore
`max_model_len=262144`, `gpu_memory_utilization=0.68`, `2048`,
`max_num_seqs=1`, and a `2 GiB` active CPU offload pool, with MTP, KV metrics,
prefix caching, SimpleCPUOffload persistence, and `/v1/trim_memory` enabled
together.

The first verified run used `DS4_DSV4_KV_OFFLOAD_SIZE=16`, but that allocates
`8 GiB` per Spark node. The default is now `2` total to keep the nodes reachable
during JIT and prefill. Larger pools are allowed only after live qualification
shows enough host headroom. Smaller pools still keep useful CPU KV blocks, but
they may not retain a full 256k prefix. Swap can help keep the OS reachable during
pressure, but it is not part of the KV capacity plan.

`VLLM_USE_SIMPLE_KV_OFFLOAD=1` is required for this persistent path. Without it,
vLLM may select the generic native `OffloadingConnector`; that connector can
serve live CPU offload but it does not own the SimpleCPUOffload persistence hooks
and can waste host RAM through rounded pinned allocations.

The persistent store must be the same absolute path on spark4 and spark5. The
local launch script exports it as `VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT` when
`DS4_DSV4_PERSIST_STORE` is set. Use a model/topology-specific store path; do
not share one store across different vLLM commits, TP layouts, model revisions,
block sizes, or cache dtypes.

## Proper KV Cache Use

There are three DSV4 cache layers, and they solve different problems:

```text
vLLM automatic prefix cache:  reuses token-identical prefix blocks while live
native CPU KV offload:        keeps HMA KV blocks outside GPU memory while live
persistent runtime mod:       reloads the native CPU offload pool after restart
```

To get hits, requests must keep the reusable prefix token-identical. Put the
large stable material first: system prompt, repository skeleton, tool schemas,
LongMem documents, and shared context. Put variable task text and small atom
suffixes after that. Keep the same model, tokenizer, chat template kwargs,
thinking mode, served model name, and lane. Whitespace changes inside the prefix
can change token hashes and miss the cache.

Operational flow:

1. Start DSV4 with the golden local launch and a persistent store.
2. Send one warm request containing the full shared prefix.
3. Send follow-up requests with the exact same prefix and only suffix changes.
4. Keep those requests sticky to the same DSV4 service lane.
5. After a restart, re-send the same prefix and confirm an external hit.

The good log lines look like:

```text
GPU KV cache size: 2,264,597 tokens
Maximum concurrency for 1,048,576 tokens per request: 2.16x
SimpleCPUOffloadWorker: restored 1264 persistent CPU blocks
SimpleCPUOffloadScheduler: restored 1264 persistent CPU blocks
DS4 persistent SimpleCPUOffload scheduler hit: ... tokens=2560 raw_tokens=2816 guard_tokens=256
External prefix cache hit rate: 82.9%
```

Bad signs:

```text
LMCacheConnectorV1Dynamic
disable_hybrid_kv_cache_manager=True
max_model_len near 45056
GPU KV cache size near 49,152 tokens
PYTHONHASHSEED unset
```

The `45056` value was the bad generic LMCache/no-HMA launch cap. It is not the
DSV4 model limit. The working DSV4 HMA launch advertises `max_model_len=1048576`.
That is the per-request serve limit. The GPU KV cache size is the aggregate pool
of live KV slots and determines concurrency/residency, not a preallocated 1M
tokens per request.

## Enable

Set a persistent store path in spark4's service environment:

```bash
DS4_DSV4_PERSIST_STORE=/home/$USER/ds4_hma_store/dsv4/simple_cpu_offload
DS4_DSV4_PERSIST_STRICT=1
DS4_DSV4_PYTHONHASHSEED=0
```

Then restart the normal DSV4 service:

```bash
ssh spark5 systemctl --user restart ds4-dsv4-local-worker.service
ssh spark4 systemctl --user restart ds4-dsv4-local-head.service
```

The local launch script exports the persistent store into vLLM as
`VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT` on both Spark ranks. Use the same
absolute path on spark4 and spark5.

Quick read-only checks after launch:

```bash
ssh spark4 curl -fsS http://127.0.0.1:8000/v1/models
ssh spark4 journalctl --user -u ds4-dsv4-local-head.service -n 200 --no-pager
ssh spark5 journalctl --user -u ds4-dsv4-local-worker.service -n 200 --no-pager
ssh spark4 find "$DS4_DSV4_PERSIST_STORE" -type f
```

## Revert

Remove or comment out `DS4_DSV4_PERSIST_STORE` and restart:

```bash
ssh spark5 systemctl --user restart ds4-dsv4-local-worker.service
ssh spark4 systemctl --user restart ds4-dsv4-local-head.service
```

Restarting without the persistent store env keeps normal native CPU offload but
disables durable disk reload. The disk store may be left in place or removed
separately.

## Required Hash Stability

`PYTHONHASHSEED=0` is required for restart-stable block hashes. Without it,
vLLM warns that block hashes may not be reproducible across processes, which
would make any disk KV index miss or, worse, point at the wrong block.

## Verification Gate

Use the same prefix before and after a restart:

1. Warm a deterministic long prefix through `deepseek-v4-flash`.
2. Confirm the store contains worker block files and `scheduler_index.json`.
3. Restart `ds4-dsv4-local-worker.service` and `ds4-dsv4-local-head.service`
   with the same store.
4. Re-run the same prefix.
5. Confirm startup logs report restored persistent CPU blocks.
6. Confirm TTFT or prefill work is lower than a cold prefix.
7. Corrupt one block file and confirm strict mode fails the request visibly.

Live spark4/spark5 gate, May 26 2026:

```text
model max_model_len:                    1048576
GPU KV cache size:                      2,264,597 tokens
Maximum concurrency at 1,048,576:       2.16x
worker restore:                         1264 persistent CPU blocks
scheduler restore:                      1264 persistent CPU blocks
restart replay prompt tokens:           3087
restart replay result:                  HTTP 200 in 7.788782s
external persistent hit log:            tokens=2560 raw_tokens=2816 guard_tokens=256
external prefix cache hit rate:         82.9%
spark4 store files after replay:        1266
spark5 store files after replay:        1265
```

The original proof replay was launched through the legacy spark4+spark5 no-Ray
Docker recipe with:

```bash
DS4_DSV4_RECIPE_SOURCE=/tmp/ds4_dsv4_persistent_trial/v2/recipes/deepseek-v4-flash-spark45.yaml
DS4_DSV4_PERSIST_MOD_SOURCE=/tmp/ds4_dsv4_persistent_trial/v2/runtime_mods/dsv4_persistent_simple_offload
DS4_DSV4_PERSIST_STORE=/tmp/ds4_hma_store_trial2/dsv4/simple_cpu_offload
/tmp/ds4_dsv4_persistent_trial/v2/scripts/ds4_dsv4_recipe_spark45.sh start
```

Host-local requalification, May 27 2026:

```text
runtime symlink:                       ~/ds4-vllm-local-8c4e588
model max_model_len:                   1048576
failed request sizes:                  1200 lines, then 112 lines / about 3k tokens
failure before store write:            yes, store stayed 16K on both nodes
kernel evidence:                       NVRM NV_ERR_NO_MEMORY during DSV4 prefill/JIT
corrective launch default attempt 1:   gpu_memory_utilization=0.75, max_num_batched_tokens=4096
attempt 1 warm request result:         32 lines pushed spark5 to 4.4 GiB swap; spark4 SSH banner stalled
current guarded launch default:        gpu_memory_utilization=0.72, max_num_batched_tokens=2048, max_num_seqs=1, kv_offload_size=4
remaining failure with MTP=2:           32-line probe OOM-killed head after JIT, store stayed 16K
remaining failure with MTP=1:           32-line probe wedged spark4 SSH/API and forced stop
current MTP guard:                      no speculative config in production launch
```
