# Unified KV Cache Request API

DS4 clients should use one high-level request contract for cache-aware memory
work. The backend decides whether that maps to Qwen LMCache, DSV4 native
SimpleCPUOffload persistence, or plain vLLM automatic prefix cache.

The request field is:

```json
{
  "input": {
    "shared_prefix": "token-identical stable prefix",
    "shared_prefix_hash": "sha256:...",
    "suffix": "small variable request",
    "kv_cache": {
      "format": "ds4-kv-cache-directive-v1",
      "backend": "auto",
      "cache_id": "qwen27/longmem/run-001/prefix-a",
      "prefix_hash": "sha256:...",
      "load": {
        "mode": "prefer",
        "transport": "remote_uri",
        "uri": "https://cache.example/ds4/kv/prefix-a",
        "bytes": 7516192768,
        "sha256": "sha256:..."
      },
      "store": {
        "mode": "write_back",
        "transport": "remote_uri",
        "uri": "https://cache.example/ds4/kv/prefix-a",
        "on_error": "fail"
      },
      "miss_policy": "compute",
      "route_affinity": "none",
      "model_fingerprint": {
        "model": "Qwen/Qwen3.6-27B-FP8",
        "tokenizer": "same revision as serving lane",
        "vllm": "experiencenow-ai/vllm commit"
      }
    }
  }
}
```

`load.mode`:

```text
skip       do not load cache data
prefer     use cache when available, compute on miss
require    fail closed if the cache cannot be loaded and validated
```

`store.mode`:

```text
skip           do not store after this request
write_through  store before completion is reported
write_back     allow asynchronous store after request completion
```

`load.transport`:

```text
inline        push a small opaque cache bundle directly in JSON
request_blob  push a side-band blob attached to the same API request
remote_uri    tell the serving node to pull from a network object
local_store   tell the serving node to pull from its local/shared cache store
```

`store.transport`:

```text
remote_uri   write to a network object
local_store  write to a node-local or shared backend store key
```

The loader validates this into:

```text
input.kv_cache_plan.format = ds4-kv-cache-plan-v1
```

The plan is what runners forward to the model gateway:

```text
Spark batch item:  item.kv_cache and item.extra_body.ds4_kv_cache
OpenAI runner:     extra_body.ds4_kv_cache
```

The queue batch key includes the cache plan hash, so requests with the same
prefix but different cache sources do not get merged into one incompatible work
group.

## Push With The Request

For small bundles:

```json
{
  "load": {
    "mode": "require",
    "transport": "inline",
    "bytes": 17,
    "sha256": "sha256:...",
    "data_b64": "b3BhcXVlIGt2IGJ1bmRsZQ=="
  }
}
```

Inline bundles are capped by `DS4_KV_CACHE_MAX_INLINE_BUNDLE_BYTES`, default
`64 MiB`. The validator checks the declared size before base64 decoding, then
checks decoded size and SHA-256. This is the memory-safety path for fuzz and
overflow testing.

For large pushed bundles, use side-band request blobs:

```json
{
  "load": {
    "mode": "require",
    "transport": "request_blob",
    "blob_id": "kv0",
    "bytes": 7516192768,
    "sha256": "sha256:..."
  }
}
```

The HTTP/multipart layer owns the blob bytes; the DS4 request body carries only
the validated manifest. This keeps the API able to route one request to one GPU
without duplicating a multi-GB cache object into queue memory.

## Pull On The Serving Node

For network pull:

```json
{
  "load": {
    "mode": "prefer",
    "transport": "remote_uri",
    "uri": "https://cache.example/ds4/kv/prefix-a",
    "bytes": 7516192768,
    "sha256": "sha256:..."
  }
}
```

Allowed remote schemes are `http`, `https`, `ds4-kv`, `lmcache`, and `s3`.
The serving node must verify the SHA-256 before injecting cache data. Fetch
time is acceptable when it replaces a long prefill.

For local or shared store pull:

```json
{
  "load": {
    "mode": "require",
    "transport": "local_store",
    "cache_key": "spark4/dsv4/prefix-a",
    "sha256": "sha256:..."
  }
}
```

`local_store` defaults `route_affinity` to `required`, because a node-local
cache key is not portable unless the backing store is actually shared.

## Backend Rules

`backend=auto` lets the serving lane choose only among backends that have
passed the live cold/warm/restart/replay gate for that model:

```text
Qwen27: APC today; LMCache is not qualified on full HMA Qwen27 yet
DSV4:   native SimpleCPUOffload/HMA persistence, not generic LMCache
APC:    token-identical prefix warming when no external KV is qualified
```

The cache payload is opaque to DS4 clients. Clients may carry or reference a
bundle, but they must not interpret tensor layout. The serving backend must
validate model revision, tokenizer, dtype, block size, TP rank, vLLM commit, and
backend-specific state before accepting a cache hit.

As of the 2026-05-27 spark7 qualification run, generic LMCache launches on
Qwen27 only after local HMA patches, but the first cold request still kills the
vLLM engine while saving KV:

```text
AttributeError: 'list' object has no attribute 'device'
lmcache/v1/gpu_connector/gpu_connectors.py:573
```

That is a correctness blocker, not a benchmark miss. Qwen27's full HMA runtime
exposes hybrid linear-attention/full-attention state that generic LMCache
currently treats like a flat attention-KV tensor list. Until a Qwen-aware
connector handles that state and passes live replay, DS4 must keep Qwen27 on
node-sticky APC instead of claiming external KV.
