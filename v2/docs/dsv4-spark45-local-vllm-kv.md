# DSV4 Spark4/5 Local vLLM KV Recipe

Status: current requalification path. The production DSV4 lane is the
host-local vLLM runtime installed from
`experiencenow-ai/vllm@d240cdbcf3de175be57c108fd9cbfce04009ec29` on top of
the known-working Docker commit
`jasl/vllm@dda4668b59567416f86956cfe7bbc1eab371a61e`. The Docker recipe is a
fallback/repro build path for this same source lineage, not the primary
runtime requirement.

The host-local service was first verified live on 2026-05-26 with the same
launch shape below:

- spark4: `ds4-dsv4-local-head.service` active
- spark5: `ds4-dsv4-local-worker.service` active
- API: `http://127.0.0.1:8000`
- model: `deepseek-v4-flash`
- reported `max_model_len`: `1048576` in the first 1M proof; current target is `262144`
- `/health` and `/v1/models`: 200 OK
- `/v1/chat/completions`: 200 OK

The durable source target in this document replaces the emergency image-copy
runtime patch used during that first proof run. After rebuilding from the pinned
vLLM commit, re-run the validation commands at the end of this file before
marking the source-built runtime healthy.

## Current Requalification Status

The 2026-05-28 requalification ran with spark7 as the worker while spark5
needed a physical reset. Observed live state after the cold/warm replay
benchmark:

```text
spark4 service: active head, RSS about 15.0G, peak 35.8G
spark7 service: active worker, RSS about 14.2G, peak 34.6G
spark4 runtime source: /home/spark4/src/vllm-b55c3b6-docker-lineage
spark7 runtime source: /home/spark7/src/vllm-b55c3b6-docker-lineage
spark4 /health: HTTP 200
spark4 /v1/models: deepseek-v4-flash, max_model_len=262144
route list: POST /v1/trim_memory present
persistent store: 2.8G on spark4 and 2.8G on spark7
```

The validation run used the 256k long-context shape:

```text
max_model_len=262144
kv_offloading_size=8
kv_cache_dtype=fp8
max_num_seqs=2
max_num_batched_tokens=8192
gpu_memory_utilization=0.8
MTP deepseek_mtp, num_speculative_tokens=2
SimpleCPUOffload persistence enabled
```

Externally driven KV replay result:

```text
prompt_tokens=6733
cold elapsed=31.621346s
warm elapsed=3.455483s
speedup=9.151064x
DS4 persistent SimpleCPUOffload scheduler hit: tokens=6144 raw_tokens=6400 guard_tokens=256
warm replay computed 589 context tokens
External prefix cache hit rate: 45.6%
```

This qualifies the host-local 256k lane for live external SimpleCPUOffload
replay speedup. A restart-persistent replay is still a separate gate. The
`/v1/trim_memory` endpoint is installed and callable; it performs local prefix
reset and `malloc_trim`, and it returns an explicit warning that
SimpleCPUOffload connector-level reset/release is not yet implemented.

## Source-Controlled Local Runtime

Runtime paths:

```text
/home/spark4/src/vllm-b55c3b6-docker-lineage
/home/spark7/src/vllm-b55c3b6-docker-lineage
/home/spark4/ds4-vllm-local
/home/spark7/ds4-vllm-local
```

The durable runtime must be built or installed from the local vLLM fork commit:

```text
https://github.com/experiencenow-ai/vllm
d240cdbcf3de175be57c108fd9cbfce04009ec29
```

That commit includes the DS4 persistent SimpleCPUOffload API commits,
request-side `cache_ref` plumbing, upstream vLLM's DSV4 native KV offload
support, and the source-controlled DeepSeek V4 loader package under:

```text
vllm/models/deepseek_v4/
```

Important source commits in that history:

```text
8c4e588f5efd45f9a119be54a82652d70be5d197 Pass request cache refs to offload cache API
357fddf [kv_offload]: Add DSv4 support (#43142)
```

Do not copy Python files out of `vllm-node-dsv4-lmcache-rankfix` for the durable
local install. That image-copy path was only a rescue step to prove the local
service could run without Docker. A production local install must be reproduced
from the pinned vLLM source commit above.

Build/install the runtime on both spark4 and spark5 into a new host-local
prefix, then atomically move the `ds4-vllm-local` symlink after the install
succeeds:

```bash
git clone https://github.com/experiencenow-ai/vllm.git ~/src/vllm-b55c3b6-docker-lineage
cd ~/src/vllm-b55c3b6-docker-lineage
git checkout d240cdbcf3de175be57c108fd9cbfce04009ec29
python3.12 -m venv ~/ds4-vllm-local-b55c3b6
export CUDA_HOME=/usr/local/cuda
export TORCH_CUDA_ARCH_LIST=12.1a
export CPATH="$HOME/standard-runtimes/python3.12-dev-extract/usr/include:$HOME/standard-runtimes/python3.12-dev-extract/usr/include/python3.12:${CPATH:-}"
~/ds4-vllm-local-b55c3b6/bin/python -m pip install -U pip wheel setuptools
~/ds4-vllm-local-b55c3b6/bin/python -m pip install -e .
ln -sfn ~/ds4-vllm-local-b55c3b6 ~/ds4-vllm-local
```

Keep the previous runtime directory intact until the new source-built service
passes `/health`, `/v1/models`, and a small `/v1/chat/completions` probe.

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
--max-model-len ${DS4_DSV4_MAX_MODEL_LEN:-262144}
--block-size 256
--kv-cache-dtype fp8
--enable-prefix-caching
--kv-offloading-size ${DS4_DSV4_KV_OFFLOAD_SIZE:-8}
--kv-offloading-backend native
--kv-cache-metrics
--enable-logging-iteration-details
--speculative-config '{"method":"deepseek_mtp","num_speculative_tokens":2}'
VLLM_USE_SIMPLE_KV_OFFLOAD=1
--no-disable-hybrid-kv-cache-manager
--enforce-eager
```

Keep the production stabilization target at `--max-model-len 262144` until the
lane passes the restart-persistent replay gate. The 1M shape exposed a much
larger live KV residency target and repeatedly pushed the Spark nodes into host
or driver memory failure during requalification.

`DS4_DSV4_KV_OFFLOAD_SIZE` is GiB of CPU KV offload buffer summed across TP
ranks. The default is `8`, which is `4 GiB` on spark4 and `4 GiB` on spark5.
This leaves room for roughly one full 1M-token DSV4 cached prefix while still
being much lighter than the first verified `16` value. Use `6` total as a
cautious setting and `4` total (`2 GiB` per node) as a recovery setting if sshd
or the API becomes unresponsive during startup. Smaller pools still allow 1M
requests, but they may not retain a full 1M prefix for reuse.

Keep `VLLM_USE_SIMPLE_KV_OFFLOAD=1`. Without it, vLLM's native backend can
select the generic `OffloadingConnector`, whose PyTorch pinned CPU allocations
may round up and whose persistent SimpleCPUOffload store hooks are not active.
The Simple connector still uses DSV4 HMA and the same `--kv-offloading-size`
budget, but it registers exact CPU tensors for DMA and keeps disk reload lazy.

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

## Swap Survival Rail

Adding swap is reasonable as a node-survival mechanism, not as inference
capacity. A `64 GiB` NVMe-backed swapfile can keep sshd/systemd responsive long
enough to stop a memory-hungry vLLM process, but if inference actively depends
on swap the service is already unhealthy. CUDA-pinned memory and pinned vLLM
offload buffers may not be swappable, so swap is not a substitute for reducing
`DS4_DSV4_KV_OFFLOAD_SIZE`.

Use low swappiness so Linux treats swap as a last-ditch pressure valve:

```bash
sudo mkdir -p /var/lib/ds4
sudo fallocate -l 64G /var/lib/ds4/ds4-survival.swap
sudo chmod 600 /var/lib/ds4/ds4-survival.swap
sudo mkswap /var/lib/ds4/ds4-survival.swap
sudo swapon /var/lib/ds4/ds4-survival.swap
echo '/var/lib/ds4/ds4-survival.swap none swap sw,pri=10 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/90-ds4-survival-swap.conf
sudo sysctl --system
```

Before enabling the DSV4 service after a bad memory event, boot with:

```bash
DS4_DSV4_KV_OFFLOAD_SIZE=4
```

Then raise to the default `8` only after `/health`, `/v1/models`, ssh, and
system logs stay stable.

## Persistent KV Store

The live path uses vLLM native KV offload plus the DS4 persistent
SimpleCPUOffload store:

```bash
export VLLM_USE_SIMPLE_KV_OFFLOAD=1
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

Startup should say `SimpleCPUOffloadConnector`, not plain `OffloadingConnector`.
If the log says `OffloadingConnector`, the persistent store environment is not
driving the connector that actually owns the CPU KV pool.

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
ssh spark4 systemctl --user start ds4-dsv4-docker-legacy.service
ssh spark4 curl -fsS http://127.0.0.1:8000/v1/models
```

`ds4-dsv4-vllm.service` is now a compatibility name for the source-built local
head service, not the Docker recipe.
