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

## DSV4 vLLM cache launch

Use the service-backed recipe:

```bash
systemctl --user start ds4-dsv4-vllm.service
```

The production recipe in `recipes/deepseek-v4-flash-spark45.yaml` uses:

```text
--max-model-len 1048576
--enable-prefix-caching
--no-disable-hybrid-kv-cache-manager
--kv-offloading-size 16
--kv-offloading-backend native
```

The verified 2026-05-26 launch reported:

```text
max_model_len:      1048576
HMA:                enabled
KV connector:       SimpleCPUOffloadConnector
CPU KV offload:     16 GiB total, 8 GiB per TP rank
GPU KV cache size:  2,088,846 tokens
1M concurrency:     1.99x
```

This is external CPU KV offload, not durable disk persistence. It preserves the
full-quality HF/vLLM DSV4 path and avoids the bad full-KV fallback.

Do not use `LMCacheConnectorV1Dynamic` for production DSV4 long context in the
current image. Live introspection showed its classes do not implement
`SupportsHMA`, and the launch log showed that adding it turns off the hybrid KV
cache manager. The result was only 49,152 GPU KV tokens and a 45,056-token
request cap.

Antirez's DS4 engine has a stronger disk KV cache because it owns the exact
DS4-specific session payload: token history, logits, raw sliding rows,
compressed rows, ratio-4 indexer rows, and compressor frontier state. That
design is the right model for durable DSV4 cache persistence, but those payloads
belong to the Antirez GGUF engine and are not compatible with vLLM's HF tensor
layout. A vLLM version of that feature needs an HMA-aware external connector
that saves and restores every DSV4 KV cache group, not a connector that flattens
the model back to full attention.

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
