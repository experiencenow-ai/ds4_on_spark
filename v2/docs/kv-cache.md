# Optional KV cache

KV cache is a launch option on the normal vLLM model profiles. It is not a
separate DS4 profile, capability class, queue backend, or model identity.

The preferred DSV4 path is a single logical vLLM serving lane with an external
KV connector:

```text
one vLLM DSV4 service on the existing spark4+spark5 TP lane
  -> LMCache connector checks reusable prompt tokens
  -> cached KV loads from CPU/disk into vLLM's paged KV buffer
  -> vLLM computes only the uncached suffix
  -> newly computed KV is stored back through the connector
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

## DSV4 LMCache launch

Plan:

```bash
PYTHONPATH=v2/src python3 -m ds4_kvcache.cli plan \
  --deployment v2/profiles/kv_cache/dsv4_spark45_lmcache.json
```

Write scripts:

```bash
PYTHONPATH=v2/src python3 -m ds4_kvcache.cli write-scripts \
  --deployment v2/profiles/kv_cache/dsv4_spark45_lmcache.json \
  --output-dir /tmp/ds4_lmcache_dsv4
```

The generated launch uses:

```json
{
  "kv_connector": "LMCacheConnectorV1Dynamic",
  "kv_role": "kv_both",
  "kv_connector_module_path": "lmcache.integration.vllm.lmcache_connector_v1"
}
```

The LMCache config is `profiles/kv_cache/lmcache_dsv4_spark45.yaml`:

```yaml
chunk_size: 256
local_cpu: true
max_local_cpu_size: 16.0
local_disk: "file:///mnt/nvme/ds4-lmcache/dsv4-spark45/"
max_local_disk_size: 512.0
```

The generated install script creates `/mnt/nvme/ds4-lmcache/dsv4-spark45`.
Move that path in the deployment JSON if a Spark uses a different local SSD
mount.

`LMCACHE_USE_EXPERIMENTAL=True` must remain an environment variable. LMCache's
configuration docs call out `LMCACHE_CONFIG_FILE` for YAML/JSON config and
`LMCACHE_LOCAL_DISK` / `max_local_disk_size` for disk offload.

The deployment references `dsv4_vllm_mtp_smartest_v1`; there is no separate
LMCache model profile.

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
DSV4 spark4+spark5 launch:     --max-model-len 200,000
DSV4 spark4+spark5 KV pool:    12,568 blocks * 256 = about 3,217,408 tokens
```

Raising `--max-model-len` does not allocate that many KV tokens for every
request. vLLM allocates from the service KV pool as requests run. The cost is
concurrency and cache residency:

```text
Qwen at 32k:   about 22 full-context requests in the observed spark7 pool
Qwen at 262k:  about 2.8 full-context requests in that same pool
DSV4 at 200k:  about 16 full-context requests in the observed spark4+spark5 pool
DSV4 at 1M:    about 3 full-context requests in that same pool
```

The operational rule is therefore:

```text
small/normal requests: keep them short and highly batched
shared long prefixes: group by shared_prefix_hash and warm once per lane
rare 1M DSV4 contexts: schedule deliberately; do not mix casually with bulk queue traffic
external KV cache: use it to preserve high-value prefixes beyond normal vLLM residency
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

First live gate:

```text
1. install lmcache in the existing vLLM runtime
2. start the normal DSV4 profile with the LMCache deployment on spark4+spark5
3. send one long shared_prefix warm request
4. send 16-128 suffix requests with the same shared_prefix
5. observe lower TTFT/prefill time on cached requests
6. verify outputs are unchanged against the same profile without the connector
```

Only after that should this launch mode become the default service launch for
the existing `smartest` profile.

## PegaFlow status

PegaFlow is not committed as a DS4 deployment yet. The published wheel does not
install on spark7's current `aarch64` Python 3.12 runtime, so adding a PegaFlow
deployment now would be a misleading variant. Revisit it only after a source
build or compatible wheel is proven on an experimental Spark.
