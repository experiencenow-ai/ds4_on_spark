# DSV4 Spark4/5 Local vLLM KV Recipe

This is the live-verified local install recipe for DeepSeek V4 Flash on
spark4/spark5. It replaces the earlier Docker-backed service with a host-local
vLLM runtime and keeps native DSV4 KV offload enabled.

Verified live on 2026-05-26:

- spark4: `ds4-dsv4-local-head.service` active
- spark5: `ds4-dsv4-local-worker.service` active
- API: `http://127.0.0.1:8000`
- model: `deepseek-v4-flash`
- reported `max_model_len`: `1048576`
- `/health` and `/v1/models`: 200 OK
- `/v1/chat/completions`: 200 OK

## Local Runtime

Runtime paths:

```text
/home/spark4/ds4-vllm-local-8c4e588
/home/spark5/ds4-vllm-local-8c4e588
/home/spark4/ds4-vllm-local -> ds4-vllm-local-8c4e588
/home/spark5/ds4-vllm-local -> ds4-vllm-local-8c4e588
```

The runtime is based on the local vLLM fork commit:

```text
8c4e588f5efd45f9a119be54a82652d70be5d197
```

The working runtime also needs upstream vLLM's DSV4 KV offload support from:

```text
357fddf [kv_offload]: Add DSv4 support (#43142)
```

Copy these files from that vLLM tree into the host runtime on both nodes:

```text
vllm/v1/kv_offload/base.py
vllm/distributed/kv_transfer/kv_connector/v1/offloading/scheduler.py
vllm/distributed/kv_transfer/kv_connector/v1/offloading/worker.py
```

The DeepSeek model rankfix used by the previous working container is still
required. Copy these from the known-good `vllm-node-dsv4-lmcache-rankfix` image:

```text
vllm/model_executor/models/deepseek_v4.py
vllm/model_executor/models/deepseek_v4_mtp.py
```

Do not replace `mxfp4.py` with the image version in this local runtime; the
image copy imports symbols that are not present in this runtime.

## Launch

Use [ds4_dsv4_spark45_local_vllm.sh](../scripts/ds4_dsv4_spark45_local_vllm.sh)
as the launch body for both systemd user units:

```text
spark4: /home/spark4/.config/systemd/user/ds4-dsv4-local-head.service
spark5: /home/spark5/.config/systemd/user/ds4-dsv4-local-worker.service
```

Start order:

```bash
ssh spark5 systemctl --user start ds4-dsv4-local-worker.service
ssh spark4 systemctl --user start ds4-dsv4-local-head.service
```

The critical launch settings are:

```text
--max-model-len 1048576
--block-size 256
--kv-cache-dtype fp8
--enable-prefix-caching
--kv-offloading-size 16
--kv-offloading-backend native
--no-disable-hybrid-kv-cache-manager
--enforce-eager
```

Keep `--block-size 256`. Changing it to 64 breaks DSV4 KV group planning. The
DSV4 offload support patch makes native offload use the DSV4 group hash size
correctly while keeping the scheduler block size at 256.

`--enforce-eager` is currently required on this local runtime because the
Torch/vLLM compile path hit:

```text
AssertionError: auto_functionalized was not removed
```

The host runtime also needs Python 3.12 headers for Triton JIT. Without root,
use the per-user extracted headers:

```text
$HOME/standard-runtimes/python3.12-dev-extract/usr/include
```

and export:

```bash
export CPATH="$HOME/standard-runtimes/python3.12-dev-extract/usr/include:$HOME/standard-runtimes/python3.12-dev-extract/usr/include/python3.12:${CPATH:-}"
```

## Persistent KV Store

The live path uses vLLM native KV offload plus the DS4 persistent
SimpleCPUOffload store:

```bash
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_ROOT=/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload
export VLLM_SIMPLE_KV_OFFLOAD_PERSIST_STRICT=1
```

Expected files after requests with offloaded blocks:

```text
/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload/scheduler_index.json
/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload/workers/10.20.0.14/worker_index.json
/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload/workers/10.20.0.14/blocks/*.pt
/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload/workers/10.20.0.15/worker_index.json
/var/tmp/ds4_hma_store/dsv4/simple_cpu_offload/workers/10.20.0.15/blocks/*.pt
```

This is not generic LMCache. It is DSV4-aware native vLLM offload state: FP8
MLA cache, sliding/indexer state, compressed KV handling, and the DSV4 KV group
layout are all handled by the vLLM DSV4 path.

## How To Use The KV Cache

For the live disk-backed mode, use node-sticky routing to the same spark4/5
service and reuse the same prefix. vLLM computes block hashes for the prefix,
checks the persistent SimpleCPUOffload store, and materializes matching CPU
offload blocks lazily.

Do not expect every short request to create useful disk KV. Blocks are persisted
when vLLM actually offloads completed KV blocks from GPU to CPU. Long repeated
prefixes are the useful case.

Do not send raw KV tensors inside the chat/completions request. The safe network
shape is two-step:

1. Route to one GPU node.
2. Push the cache package to that node's cache service.
3. Get back a small `cache_ref`.
4. Send the generation request to the same node with:

```json
{
  "extra_args": {
    "kv_transfer_params": {
      "cache_ref": "cachepkg_..."
    }
  }
}
```

The vLLM client code recognizes:

```text
cache_ref
simple_kv_cache_ref
ds4_cache_ref
```

when `VLLM_SIMPLE_KV_OFFLOAD_PERSIST_API_URL` is set. The live service verified
here is disk-backed mode; do not claim API-backed `cache_ref` mode is live until
a node-local cache API service is started and verified.

## External API Mode

The intended external cache API is small and request-scoped:

```text
POST /v1/kv/lookup
POST /v1/kv/materialize
POST /v1/kv/store/prepare
POST /v1/kv/store/commit
POST /v1/kv/scheduler/commit
```

`/v1/kv/ingest` is the gateway-facing push endpoint for bundled cache packages.
The gateway should call it before the generation request, then include the
returned `cache_ref` in the request.

API mode must not enumerate all lifetime CPU blocks at vLLM startup. It should
only answer lookups for the current request's block hashes and materialize the
exact selected `(cpu_block_id, block_hash, cache_ref)` pairs.

## Validation Commands

```bash
ssh spark4 curl -fsS http://127.0.0.1:8000/health
ssh spark4 curl -fsS http://127.0.0.1:8000/v1/models
```

Expected model response includes:

```text
"id":"deepseek-v4-flash"
"max_model_len":1048576
```

Minimal inference probe:

```bash
scp /tmp/ds4_chat_probe.json spark4:/tmp/ds4_chat_probe.json
ssh spark4 curl -fsS -X POST http://127.0.0.1:8000/v1/chat/completions -H Content-Type:application/json --data-binary @/tmp/ds4_chat_probe.json
```

First inference may be slow because Triton JIT compiles DSV4 kernels.

## Rollback

If the local runtime fails, stop the local units and restore the prior
Docker-backed service:

```bash
ssh spark4 systemctl --user stop ds4-dsv4-local-head.service
ssh spark5 systemctl --user stop ds4-dsv4-local-worker.service
ssh spark4 systemctl --user start ds4-dsv4-vllm.service
ssh spark4 curl -fsS http://127.0.0.1:8000/v1/models
```
