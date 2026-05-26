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
