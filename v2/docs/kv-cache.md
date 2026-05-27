# Optional KV cache

KV cache is a launch option on the normal vLLM model profiles. It is not a
separate DS4 profile, capability class, queue backend, or model identity.

The preferred DSV4 path is a single logical vLLM serving lane with vLLM's
hybrid KV cache manager enabled:

```text
one vLLM DSV4 service on the existing spark4+spark5 TP lane
  -> DSV4 HMA keeps sliding/compressed cache groups small
  -> prefix caching reuses token-identical prompt blocks while resident
  -> native CPU KV offload moves reusable blocks out of GPU memory
  -> vLLM computes only the uncached suffix when the prefix still matches
```

The DSV4 lane may use tensor parallel workers across spark4+spark5. That is
still one model-serving service, not two model instances and not a
prefiller/decoder split.

Centaur still sends normal DS4 inference requests. The queue groups lattice
requests by `shared_prefix_hash`, and `queue-warm-prefixes` can seed a skeleton
prefix before the real atom suffixes arrive.

## What is proven

The prefix-cache mechanism is live-proven on the experimental spark7 Qwen27
lane:

```text
model: Qwen/Qwen3.6-27B-FP8
prompt: 30,029 tokens
cold request: 46.190s
warm same-prefix request: 0.286s
warm request prompt tokens from local cache: 29,792
warm request newly computed prompt tokens: 237
```

This proves the useful part of the design: when the long prefix is
token-identical, vLLM reuses cached KV and computes only the uncached suffix.
DSV4 has to be measured on the shared spark4+spark5 production lane, so use
vLLM counters rather than wallclock when other users are active:

```text
vllm:prefix_cache_queries_total
vllm:prefix_cache_hits_total
vllm:prompt_tokens_by_source_total{source="local_compute"}
vllm:prompt_tokens_by_source_total{source="local_cache_hit"}
vllm:prompt_tokens_by_source_total{source="external_kv_transfer"}
```

## Qwen27 LMCache path

Qwen uses ordinary vLLM KV tensors, so it can use LMCache directly. Keep this
separate from DSV4: DSV4 needs its custom/native HMA path, but Qwen27 should
prove external KV through LMCache MP first.

The shape follows LMCache MP's documented pattern: run `lmcache server`, then
launch vLLM with `LMCacheMPConnector` and `kv_connector_extra_config` pointing
at that server. See the LMCache MP quickstart and configuration reference:
<https://docs.lmcache.ai/mp/quickstart.html> and
<https://docs.lmcache.ai/mp/configuration.html>.

The required vLLM fork revision for both DSV4 and Qwen27 is:

```text
https://github.com/experiencenow-ai/vllm
d523ead071132cd291e66e3dfd68f55446c27357
```

The experimental launch profile is:

```text
profiles/kv_cache/qwen27_lmcache_mp_spark7.json
```

It starts one LMCache MP server on the same Spark as the Qwen vLLM service and
connects vLLM through `LMCacheMPConnector`:

```text
Qwen27 vLLM:       http://127.0.0.1:18110
vLLM runtime:      /home/spark7/ds4-vllm-local from experiencenow-ai/vllm@d523ead071132cd291e66e3dfd68f55446c27357
LMCache data port: 127.0.0.1:5555
LMCache HTTP port: 127.0.0.1:18080
L1 CPU cache:      16 GiB, lazy init, LRU
L2 store:          /mnt/nvme/ds4_lmcache/qwen27/l2 via POSIX NIXL store
```

On spark7 the LMCache package currently has to build from source. The generated
install script builds a pinned `lmcache==0.4.5` wheel with
`--no-build-isolation --no-deps`, then installs that wheel with `--no-deps` so a
running vLLM environment does not unexpectedly churn shared dependencies.

Plan it through the same DS4 KV tool used for DSV4:

```bash
PYTHONPATH=src python3 -m ds4_tools.cli invoke \
  --registry tools/registry.jsonl \
  --tool-id tool:ds4.kvcache.plan \
  --arguments '{"deployment":"profiles/kv_cache/qwen27_lmcache_mp_spark7.json"}'
```

Write launch scripts:

```bash
PYTHONPATH=src python3 -m ds4_kvcache.cli write-scripts \
  --deployment profiles/kv_cache/qwen27_lmcache_mp_spark7.json \
  --output-dir /tmp/ds4_qwen27_lmcache_mp
```

Start order:

```bash
/tmp/ds4_qwen27_lmcache_mp/00_install_kv_cache_deps.sh
/tmp/ds4_qwen27_lmcache_mp/start_lmcache_server.sh
/tmp/ds4_qwen27_lmcache_mp/start_vllm_cache.sh
```

The Qwen acceptance gate is:

```text
1. launch LMCache MP server and Qwen27 vLLM with LMCacheMPConnector
2. confirm /v1/models returns Qwen/Qwen3.6-27B-FP8
3. send one long shared_prefix warm request
4. send same-prefix suffix requests routed to that Spark
5. verify external_kv_transfer or LMCache hit counters/logs
6. restart vLLM while keeping LMCache/L2 intact
7. repeat the same-prefix request and verify lower TTFT/prefill without full recompute
```

Use the same high-level request shape for both Qwen and DSV4: clients provide
stable prefix text or a `kv_cache_ref` to stable prefix text, and DS4 routes the
request to a compatible backend. The backend owns raw KV bytes. Qwen backs that
contract with LMCache; DSV4 backs it with the custom/native HMA offload path.

## DSV4 vLLM cache launch

Use the source-built local vLLM services:

```bash
ssh spark5 systemctl --user start ds4-dsv4-local-worker.service
ssh spark4 systemctl --user start ds4-dsv4-local-head.service
```

The compatibility `ds4-dsv4-vllm.service` on spark4 launches the same local
head script. `ds4-dsv4-docker-legacy.service` is rollback-only.

The production launch body is
`scripts/ds4_dsv4_spark45_local_vllm.sh`, built from:

```text
https://github.com/experiencenow-ai/vllm
d523ead071132cd291e66e3dfd68f55446c27357
```

It uses:

```text
--max-model-len 1048576
--enable-prefix-caching
--no-disable-hybrid-kv-cache-manager
--kv-offloading-size ${DS4_DSV4_KV_OFFLOAD_SIZE:-8}
--kv-offloading-backend native
VLLM_USE_SIMPLE_KV_OFFLOAD=1
```

The verified 2026-05-26 launch reported:

```text
max_model_len:      1048576
HMA:                enabled
KV connector:       SimpleCPUOffloadConnector
CPU KV offload:     8 GiB total default, 4 GiB per TP rank
GPU KV cache size:  2,088,846 tokens
1M concurrency:     1.99x
```

`DS4_DSV4_KV_OFFLOAD_SIZE=16` was the first verified value. The default is `8`
total because a full 1M-token DSV4 cached prefix is roughly 7 GiB across the TP
lane. `6` total is a cautious mode, and `4` total is the recovery setting when
Spark nodes are memory-sensitive. NVMe swap can help the OS survive pressure
long enough to kill vLLM, but swap is not KV capacity and should not be used for
normal inference.

This is external CPU KV offload. It preserves the full-quality HF/vLLM DSV4 path
and avoids the bad full-KV fallback. Durable restart persistence is handled by
the native-offload runtime mod in `docs/dsv4-persistent-simple-offload.md`,
which extends vLLM's HMA-aware `SimpleCPUOffloadConnector` instead of replacing
it with LMCache.

The `VLLM_USE_SIMPLE_KV_OFFLOAD=1` environment variable is required. Otherwise
the same native backend can select the generic `OffloadingConnector`; that path
does not activate the SimpleCPUOffload persistent store and may spend extra host
RAM through rounded pinned allocations.

Proper DSV4 KV use is:

```text
1. keep the spark4+spark5 service as one no-Ray TP=2 DSV4 lane
2. keep HMA enabled and use native SimpleCPUOffloadConnector
3. set PYTHONHASHSEED=0 for restart-stable block hashes
4. set DS4_DSV4_PERSIST_STORE for disk persistence of the CPU offload pool
5. warm one token-identical shared prefix before suffix fanout
6. route suffix requests stickily to the same DSV4 lane
7. verify external prefix cache hits in vLLM logs or metrics
```

The persistent runtime mod is not a replacement for prefix discipline. It can
reload CPU offload blocks after restart, but it still keys those blocks by vLLM
block hashes. A reused LongMem prefix must be byte/token-identical across warm
and replay requests.

Do not use `LMCacheConnectorV1Dynamic` for production DSV4 long context. Live
introspection showed its classes do not implement
`SupportsHMA`, and the launch log showed that adding it turns off the hybrid KV
cache manager. The result was only 49,152 GPU KV tokens and a 45,056-token
request cap.

Antirez's DS4 engine has a stronger disk KV cache because it owns the exact
DS4-specific session payload: token history, logits, raw sliding rows,
compressed rows, ratio-4 indexer rows, and compressor frontier state. That
design is the right model for durable DSV4 cache persistence, but those payloads
belong to the Antirez GGUF engine and are not compatible with vLLM's HF tensor
layout. The first vLLM implementation path is the persistent native CPU-offload
mod because the live connector already sees the compressed/sliding HMA groups
that DSV4 actually uses. The pinned-only dynamic connector scaffold still lives
in `docs/dsv4-hma-persistent-kv.md` and `profiles/hma/dsv4_hma_persistent.json`
for future upstream connector work.

## Limits and scheduling constraints

There are three different limits:

```text
model limit:        what the model/tokenizer says it can address
serve limit:        the vLLM --max-model-len chosen for this service launch
aggregate KV pool:  total live/cached KV-token slots available in the service
```

Live observations from the current Sparks:

```text
Qwen27/Qwen35 model_max_length: 262,144 tokens
Qwen27 spark7 service launch:  --max-model-len 32,768
Qwen27 spark7 KV pool:         about 733,866 tokens

DSV4 max_position_embeddings:  1,048,576 tokens
DSV4 spark4+spark5 launch:     --max-model-len 1,048,576
DSV4 spark4+spark5 KV pool:    2,088,846 tokens
```

Raising `--max-model-len` does not allocate that many KV tokens for every
request. vLLM allocates from the service KV pool as requests run. The cost is
concurrency and cache residency:

```text
Qwen at 32k:   about 22 full-context requests in the observed spark7 pool
Qwen at 262k:  about 2.8 full-context requests in that same pool
DSV4 at 1M:    about 2 full-context requests in the observed spark4+spark5 pool
```

The operational rule is therefore:

```text
small/normal requests: keep them short and highly batched
shared long prefixes: group by shared_prefix_hash and warm once per lane
rare 1M DSV4 contexts: schedule deliberately; do not mix casually with bulk queue traffic
external CPU KV offload: use it to preserve high-value prefixes beyond normal GPU residency
```

The `shared_prefix` must be byte/token-identical. Put repo skeletons,
instructions, tool schemas, and LongMem documents before the variable suffix.
Changing whitespace, chat template arguments, model profile, adapter, or
thinking mode can defeat cache hits.

## Why not raw blobs

Do not expose raw KV tensors to Centaur. KV layout is tied to model revision,
tokenizer, dtype, attention backend, tensor-parallel rank, block size, vLLM
version, and hybrid DeepSeek cache layout. The DS4 API should expose stable
cache keys and prefix grouping; the vLLM connector should own the bytes.

## Acceptance

Persistent external KV cache gate:

```text
1. choose or build a vLLM connector whose class implements SupportsHMA
2. start DSV4 with --no-disable-hybrid-kv-cache-manager and that connector
3. verify startup reports HMA enabled and max_model_len=1048576
4. send one long shared_prefix warm request
5. send 16-128 suffix requests with the same shared_prefix
6. observe external-cache reads and lower TTFT/prefill time on cached requests
7. verify outputs are unchanged against the same HF/vLLM DSV4 profile
```

Only after that should durable external cache become the default service launch
for the existing `smartest` profile.

## PegaFlow status

PegaFlow is not committed as a DS4 deployment yet. The published wheel does not
install on spark7's current `aarch64` Python 3.12 runtime, so adding a PegaFlow
deployment now would be a misleading variant. Revisit it only after a source
build or compatible wheel is proven on an experimental Spark.
