# DSV4 Persistent Native HMA Offload

DSV4 persistent KV is implemented on top of vLLM's native
`SimpleCPUOffloadConnector`. This is deliberately not an LMCache launch. The
live DSV4 path already stores the correct HMA KV block tensors in native CPU
offload; the DS4 patch makes that CPU offload pool durable across vLLM
restarts.

Current production target:

```text
launch script: scripts/ds4_dsv4_spark45_local_vllm.sh
systemd units: ds4-dsv4-local-head.service, ds4-dsv4-local-worker.service
vLLM fork:     https://github.com/experiencenow-ai/vllm
vLLM base:     dda4668b59567416f86956cfe7bbc1eab371a61e
vLLM target:   d240cdbcf3de175be57c108fd9cbfce04009ec29, PR #6
```

The earlier runtime mod remains in `runtime_mods/` as the historical proof and
rollback substrate. The production Docker image should build the vLLM source PR
directly; launch-time runtime patching is only an explicit emergency fallback.
The primary production lane is the host-local editable install from that same
source lineage, not a copied Docker package.

## What Is Patched

The Docker-lineage fork carries the SimpleCPUOffload persistence seams in vLLM
source. The Spark Docker recipe wrapper can still install the old launch-time
runtime mod only when `DS4_DSV4_ENABLE_PERSISTENT_RUNTIME_MOD=1`:

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
nodes:                         spark4 + spark5 as one no-Ray TP=2 service, or spark4 + spark7 while spark5 is unavailable
historical proof vLLM ref:     dda4668b59567416f86956cfe7bbc1eab371a61e
current source vLLM ref:       d240cdbcf3de175be57c108fd9cbfce04009ec29
runtime:                       host-local editable install from experiencenow-ai/vllm Docker lineage
max_model_len:                 262144
MTP speculative decoding:      enabled, deepseek_mtp with 2 speculative tokens
block_size:                    256
hybrid KV manager:             enabled
prefix caching:                enabled
KV cache dtype:                fp8
GPU memory utilization:        0.8
prefill chunk:                 max_num_batched_tokens=8192
max active sequences:          2
KV offload backend:            native
KV offload size:               8 GiB total default, 4 GiB per TP rank
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
--gpu-memory-utilization 0.8
--max-num-seqs 2
--max-num-batched-tokens 8192
--kv-offloading-size 8
--kv-offloading-backend native
--kv-cache-metrics
--enable-logging-iteration-details
--speculative-config '{"method":"deepseek_mtp","num_speculative_tokens":2}'
VLLM_USE_SIMPLE_KV_OFFLOAD=1
```

The host-local Docker-lineage runtime was requalified on May 28 2026 on
spark4/spark7 with the context capped at 256k. The prior "256k failed" symptom
was caused by stale native extension ABI and Cutlass DSL dependency drift in
the local install, not by an inherent 256k DSV4 source regression. The current
target is therefore the source-built Docker lineage capped at 256k, with MTP,
KV metrics, prefix caching, SimpleCPUOffload persistence, and
`/v1/trim_memory` enabled together.

The first verified Docker run used an 8 GiB total CPU offload pool, 4 GiB per
Spark node. Keep that Docker shape for the stabilization run. Larger pools are
allowed only after live qualification shows enough host headroom. Smaller pools
still keep useful CPU KV blocks, but they may not retain a full 256k prefix.
Swap can help keep the OS reachable during pressure, but it is not part of the
KV capacity plan.

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
DS4_DSV4_PERSIST_STORE=/mnt/nvme/ds4_hma_store/dsv4/simple_cpu_offload
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

Rejected host-local mainline requalification, May 27 2026:

```text
runtime tested:                        experiencenow-ai/vllm mainline after large DeepSeek/MoE/MTP drift
model max_model_len:                   262144
launch included:                       MTP=2, KV metrics, SimpleCPUOffload persistence, /v1/trim_memory
failure before API readiness:          yes
spark4 evidence:                       OOM killed, 37.5G cgroup memory peak, 2.3G swap peak
spark5 evidence:                       SSH banner timeout while worker was loading/finalizing
source diff from Docker proof:         over 1,200 files, not a narrow KV/trim patch
production correction:                 return to Docker lineage plus PR #6 only
```
