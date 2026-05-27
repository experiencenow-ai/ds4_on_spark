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

## What Is Proven

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
It does not prove LMCache/external KV for Qwen27.

The 2026-05-27 live Qwen27 LMCache qualification on spark7 did not pass. After
patching LMCache's vLLM connector to implement the HMA hook, and after allowing
Qwen's shifted HMA views, the first cold request still crashed inside LMCache:

```text
AttributeError: 'list' object has no attribute 'device'
lmcache/v1/gpu_connector/gpu_connectors.py:573
```

No Qwen27 LMCache speedup number exists yet because the cold request never
completed. The current Qwen27 answer is therefore APC-only: node-sticky,
token-identical prefix reuse inside the live vLLM process.

DSV4 has to be measured on the shared spark4+spark5 production lane, so use
vLLM counters rather than wallclock when other users are active:

```text
vllm:prefix_cache_queries_total
vllm:prefix_cache_hits_total
vllm:prompt_tokens_by_source_total{source="local_compute"}
vllm:prompt_tokens_by_source_total{source="local_cache_hit"}
vllm:prompt_tokens_by_source_total{source="external_kv_transfer"}
```

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
75358b5ef269050fbbf0d34a1e9772d8c56ac7c7
```

It uses:

```text
--max-model-len ${DS4_DSV4_MAX_MODEL_LEN:-262144}
--enable-prefix-caching
--no-disable-hybrid-kv-cache-manager
--kv-offloading-size ${DS4_DSV4_KV_OFFLOAD_SIZE:-2}
--kv-offloading-backend native
--kv-cache-metrics
--enable-logging-iteration-details
--speculative-config '{"method":"deepseek_mtp","num_speculative_tokens":2}'
VLLM_USE_SIMPLE_KV_OFFLOAD=1
```

The verified 2026-05-26 1M Docker launch reported:

```text
max_model_len:      1048576
HMA:                enabled
KV connector:       SimpleCPUOffloadConnector
CPU KV offload:     8 GiB total default, 4 GiB per TP rank
GPU KV cache size:  2,088,846 tokens
1M concurrency:     1.99x
```

`DS4_DSV4_KV_OFFLOAD_SIZE=16` was the first verified value for the 1M Docker
proof. The current source-built 256k target defaults to `2` total because the
1M host-local profile exhausted host/NVIDIA driver memory during
requalification. Larger pools must be requalified live. NVMe swap can help the
OS survive pressure long enough to kill vLLM, but swap is not KV capacity and
should not be used for normal inference.

This is external CPU KV offload. It preserves the full-quality HF/vLLM DSV4 path
and avoids the bad full-KV fallback. Durable restart persistence is handled by
the native-offload runtime mod in `docs/dsv4-persistent-simple-offload.md`,
which extends vLLM's HMA-aware `SimpleCPUOffloadConnector` instead of replacing
it with LMCache.

The DSV4 external-KV benchmark gate is not satisfied by startup logs. A passing
run must include:

```text
cold long-prefix request: 200 OK and persisted offload blocks
restart: both spark4 and spark5 services restarted from the same source runtime
replay: same prefix returns 200 OK
evidence: external_kv_transfer or DS4 persistent hit log lines
result: TTFT/prefill delta versus cold request
```

The 2026-05-27 requalification attempt could not produce that benchmark because
spark5 was unreachable from the control host, and spark4 was not serving
`/health` while waiting on the grouped TP lane.

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

## Unified request API

Use `docs/kv-cache-api.md` for client-level cache requests. The unified field is
`input.kv_cache`; it supports:

```text
push inline:       small opaque bundle inside the JSON request
push request_blob: side-band blob attached to the one request being routed
pull remote_uri:   serving node fetches a verified network object
pull local_store:  serving node reads a local/shared cache key
store:             write-through or write-back after compute
```

The API carries opaque bundles or references, not client-interpreted tensor
layout. KV layout is still tied to model revision, tokenizer, dtype, attention
backend, tensor-parallel rank, block size, vLLM version, and DSV4 hybrid cache
state. The serving backend must validate those fingerprints before accepting a
hit.

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
