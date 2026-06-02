# Static Spark Topology

The production Spark pool is intentionally static. Centaur and DS4 services should not treat the eight Sparks as a model zoo that loads and unloads models per request.

## Allocation

| Spark | Role | Resident profiles |
|---|---|---|
| spark0 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1` |
| spark1 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1` |
| spark2 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1` |
| spark3 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1` |
| spark4 | DSV4 vLLM grouped lane half | `dsv4_vllm_mtp_smartest_v1` |
| spark5 | DSV4 vLLM grouped lane half | `dsv4_vllm_mtp_smartest_v1` |
| spark6 | Qwen production lane | `qwen3_6_27b_fp8_efficient_v1` |
| spark7 | Experimental on-demand lane | none |

This gives the service a normal production view of:

- 5 Qwen27 lanes for `efficient` work;
- 1 DSV4 vLLM grouped lane for `smartest` chat/tool/reasoning work, consuming both spark4 and spark5;
- 1 experimental on-demand lane on spark7.

No model is dynamically ejected from production Sparks. Spark6 is now a normal
Qwen resident lane. Spark7 is intentionally experimental and may lazy-load
models for probes without becoming a production resident lane.
The Qwen35/fastest profile remains in the profile registry for later use, but
it is parked and is not a documented production resident model for now.

KV-cache experiments should use `ds4_kvcache` deployment files. They do not add
resident profiles to the topology.

## Memory Trim Control

Client-level memory relief must go through the topology-aware API documented in
`docs/spark-trim-memory-api.md`. Use `tool:spark.trim_memory` or
`ds4_infer.cli trim-spark-memory`; do not bake raw Spark-local curl commands
into clients.

The topology declares `trim_default_profiles_by_node` so a request like
`{"node":"spark0","execute":true}` resolves to the Qwen27 trim contract without
asking the caller to know the local port. Spark7 has no resident default, so
experimental trims must pass `profile_id` or `base_url`. The spark4+spark5 DSV4
group resolves trim traffic to the contract head node, spark4, even when the
caller asks to relieve spark5.

## DSV4 Launch Rule

The spark4+spark5 DSV4 lane must use the source-built, host-local vLLM runtime
with vLLM's hybrid KV cache manager enabled. This is not an interchangeable
implementation detail. Each Spark has one GPU, and the working DSV4 result uses
explicit multi-node ranks, not Ray placement groups.

Canonical launch path:

```text
spark5: deploy/systemd-user/ds4-dsv4-local-worker.service
  -> scripts/ds4_dsv4_spark45_local_vllm.sh worker

spark4: deploy/systemd-user/ds4-dsv4-local-head.service
  -> scripts/ds4_dsv4_spark45_local_vllm.sh head
```

The compatibility unit `ds4-dsv4-vllm.service` also launches the same
source-built spark4 head script. The old Docker service has been moved to
`ds4-dsv4-docker-legacy.service` and is rollback-only.

Start worker first, then head:

```bash
ssh spark5 systemctl --user start ds4-dsv4-local-worker.service
ssh spark4 systemctl --user start ds4-dsv4-local-head.service
```

The runtime must come from the local vLLM fork:

```text
vLLM fork:   https://github.com/experiencenow-ai/vllm
vLLM commit: c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34
runtime:     ~/ds4-vllm-local-c6e55a8
symlink:     ~/ds4-vllm-local
```

That source commit includes the DSV4 loader, upstream DSV4 native KV offload,
the DS4 persistent SimpleCPUOffload/cache-ref API, the trim endpoint, and the
Qwen27 LMCache MP runtime docs/tooling. Do not recreate the service by copying
Python files out of the old
`vllm-node-dsv4-lmcache-rankfix` image.

The required serving command shape is:

```text
TP=2, PP=1, EP enabled
MTP speculative decoding enabled: deepseek_mtp, 2 speculative tokens
max_model_len=262144
max_num_seqs=1
max_num_batched_tokens=2048
gpu_memory_utilization=0.68
block_size=256
fp8 KV cache
hybrid KV cache manager enabled
SimpleCPUOffloadConnector via --kv-offloading-size ${DS4_DSV4_KV_OFFLOAD_SIZE:-2} --kv-offloading-backend native
KV cache metrics and iteration details enabled
VLLM_USE_SIMPLE_KV_OFFLOAD=1
NCCL_IB_DISABLE=1, NCCL/Gloo/TP sockets pinned to enP7s7
--enforce-eager
node ranks: spark4 rank 0, spark5 rank 1 --headless
```

`LMCacheConnectorV1Dynamic` turns off vLLM's hybrid KV cache manager in this
runtime. That makes DSV4 compressed/sliding cache groups behave like ordinary
full KV cache groups, which collapses the useful long-context launch back to a
roughly 45k-token request cap. Do not use LMCache dynamic for production DSV4
long context unless a live probe proves that the connector implements
`SupportsHMA` and the startup log still reports HMA enabled.

The live verified launch on 2026-05-26 exposed:

```text
API endpoint:       http://10.20.0.14:8000/v1
served model name:  deepseek-v4-flash
max_model_len:      1048576
runtime target:     experiencenow-ai/vllm@c6e55a80d213ba2652ab9a7d5d0aacf01cbccd34
HMA:                enabled (disable_hybrid_kv_cache_manager=False)
KV connector:       SimpleCPUOffloadConnector
CPU KV offload:     8 GiB total default, 4 GiB per TP rank
GPU KV cache size:  2,088,846 tokens
1M concurrency:     1.99x
smoke response:     dsv4-1m-ok
```

The previous LMCache dynamic launch is explicitly not a valid long-context
artifact:

```text
connector:          LMCacheConnectorV1Dynamic
HMA:                disabled by kv-transfer-config
GPU KV cache size:  49,152 tokens
max_model_len:      45,056
```

Do not replace this with a Ray vLLM service unless a new benchmark proves the
Ray path reaches API readiness and matches the source-built local lane.

The May 27 2026 requalification showed the 1M-context host-local runtime
exhausting NVIDIA driver/system memory during a cold request. The production
lane is therefore capped at 256k while MTP, prefix caching, native
SimpleCPUOffload, persistent KV hooks, metrics, and `/v1/trim_memory` are
qualified together.

Antirez's DS4 engine proves that durable, disk-backed DSV4 KV persistence is
possible when the runtime owns the DS4-specific compressed session payload.
That is not the same as generic LMCache support in vLLM. To get persistent
external KV cache with full-quality HF/vLLM DSV4, extend an HMA-aware connector
that already sees the compressed/sliding groups. The current reversible path is
`docs/dsv4-persistent-simple-offload.md`, which persists vLLM's native
`SimpleCPUOffloadConnector` CPU block pool instead of flattening DSV4 through
LMCache.

The legacy Docker artifacts remain only for rollback and historical comparison:

```text
deploy/systemd-user/ds4-dsv4-docker-legacy.service
scripts/ds4_dsv4_recipe_spark45.sh
recipes/deepseek-v4-flash-spark45.yaml
```

Do not use those artifacts to recreate the current source-built DSV4 lane.

Latest recovery status after the bad Ray launch attempt:

```text
checked_at: 2026-05-26 14:28 KST
spark4: rebooted, up 8 minutes, GPU clear
spark4 legacy ds4-dsv4-vllm.service at that time: installed, enabled, inactive
spark4 ds4-dsv4-ray-head.service: disabled, inactive
spark5: GPU clear
spark5 ds4-dsv4-ray-worker.service: disabled, inactive
spark4 local port 8000: closed because DSV4 is not currently running
```

This means the cluster was clean for a source-built local DSV4 start, and the
broken Ray DSV4 services were no longer part of the startup path.

## Policy

The inference scheduler owns node assignment. Centaur requests a capability and job class; it does not target a Spark directly.

Normal queued requests prefer resident production lanes. Efficient Qwen requests
therefore spread across spark0-3 and spark6. `smart`/`smartest` DSV4 requests
use the spark4+spark5 grouped vLLM lane unless explicitly pinned to a legacy
non-production profile. Dynamic loading is allowed only for unmatched
experimental requests routed to spark7, not for production model ejection.

Qwen capacity planning uses aggregate batched decode. Single-stream Qwen27
decode is about 8 generated tok/s on this Spark shape, while the production
launch cap is `max_num_seqs=12`. Do not revive the old 64-way gateway default.
Keep batch workers deep enough to feed vLLM continuous batching before judging
lane throughput.

The topology is stored in:

```text
profiles/topology/static_sparks.json
```

## Startup Warmup

Each production Spark should run the same startup command after reboot:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli startup-models \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --node-id spark0
```

The command reads this topology and warms only that node's resident profiles.
Spark0-3 and spark6 warm Qwen27 only, spark4 warms the deployed grouped DSV4
vLLM lane, spark5 records itself as the secondary half of that group, and
spark7 is a clean no-op because it is on demand. Production lanes use the
default `127.0.0.1:8000` gateway.

The user service template is in:

```text
v2/deploy/systemd-user/ds4-startup-models.service
```

Inspect capacity:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli topology \
  --topology profiles/topology/static_sparks.json \
  --capacity
```

Submit a request batch through the topology planner:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests requests.jsonl \
  --batch-id topology-smoke
```

Queue submission records selected nodes. Individual responses include the selected node assignment. The DSV4 vLLM profile appears as `spark4+spark5` with `node_ids=["spark4", "spark5"]`. The Spark runner now fails closed when a live model call has no selected node.

## Why this exists

The earlier approach made every local LLM attempt an experiment. Batch size, thinking budget, backend, and model loading decisions leaked into Centaur. Static residency turns Spark inference into a service boundary: production lanes are boring and measurable, and the scheduler does not unload resident models for lopsided short-term usage.
