# KV Cache Live Validation Status

Unit tests and request-shape tests prove only the DS4 API plumbing. External KV
has two live gates: same-process external replay, and restart-persistent
external replay. Full persistent KV is considered live for a model only after a
cold/warm/restart/replay run finishes on the real serving lane and reports an
external-cache hit plus a TTFT/prefill improvement.

## Required Benchmark

For each model/backend pair:

```text
1. launch the exact production runtime
2. verify model, tokenizer, vLLM commit, dtype, block size, TP layout
3. send a cold long-prefix request and record TTFT/prefill time
4. verify cache blocks were stored outside GPU KV
5. restart the serving process without deleting the external store
6. send the exact same prefix plus a small suffix
7. verify external-cache hit counters or DS4 persistent-hit logs
8. record replay TTFT/prefill time and speedup
```

Do not accept a benchmark if the first request crashes, if replay falls back to
full recompute, or if the only evidence is that a connector was configured.

## 2026-05-27 Qwen27 LMCache Result

Node and launch:

```text
node: spark7
model: /home/spark7/models/hf/Qwen/Qwen3.6-27B-FP8
max_model_len: 262144
max_num_seqs: 12
max_num_batched_tokens: 32768
gpu_memory_utilization: 0.50
prefix caching: enabled
HMA: enabled
LMCache: 0.4.5
```

Observed sequence:

```text
initial launch: failed because LMCacheConnectorV1 did not implement SupportsHMA
local patch: made LMCacheConnectorV1 implement SupportsHMA
second failure: LMCache rejected shifted dim-0-padded Qwen HMA tensors
local patch: accepted shifted views because data_ptr() already includes offset
third failure: first cold request killed EngineCore during LMCache save
```

Final blocker:

```text
AttributeError: 'list' object has no attribute 'device'
lmcache/v1/gpu_connector/gpu_connectors.py:573
```

Interpretation: generic LMCache still assumes flat attention KV tensors. The
full Qwen27 HMA runtime exposes hybrid state, including many linear-attention
layers, where the KV cache object is nested. Qwen27 LMCache is therefore not
qualified and has no speedup number yet. Use node-sticky APC for Qwen27 until a
Qwen-aware connector passes this gate.

## 2026-05-27 DSV4 Persistent KV Result

Node and intended launch:

```text
nodes: spark4 + spark5 grouped TP lane
model: deepseek-ai/DeepSeek-V4-Flash
served model: deepseek-v4-flash
max_model_len: 1048576 during failed run; next qualification target is 262144
kv_cache_dtype: fp8
HMA: enabled
native CPU KV offload: enabled
expected connector: SimpleCPUOffloadConnector
```

Observed live state:

```text
spark4 service before probe: active, NRestarts=0
spark5 service before probe: active, NRestarts=0
spark4 runtime symlink: /home/spark4/ds4-vllm-local-8c4e588
spark5 runtime symlink: /home/spark5/ds4-vllm-local-8c4e588
latest spark4 launch: speculative_config=None, so MTP was off
spark4 /health before probe: HTTP 200
spark4 /v1/models before probe: deepseek-v4-flash, max_model_len=1048576
```

Smoke probe:

```text
prompt_tokens: 675
elapsed_s: 18.157
prefill_tokens: 675
prefill_time_s: 18.109
external_cache_hit_pct: 0
store files after probe: 0 on spark4, 0 on spark5
```

A larger 48-line prefix request returned HTTP 200 but destabilized the grouped
lane shortly after completion. spark4 logged repeated shared-memory broadcast
timeouts, then systemd recorded an OOM kill:

```text
result: oom-kill
memory peak: 38.4G
swap peak: 2.5G
restart counter: 1
```

The documented emergency trim route was also missing from the live runtime:

```text
POST /v1/trim_memory?... -> 404 before patch
```

This is not a valid speedup proof. DSV4 persistent external KV remains
unqualified for this re-run until spark5 is reachable, `/v1/trim_memory` is
installed on both ranks, and a replay produces external-hit evidence plus a
TTFT/prefill improvement.

## 2026-05-28 DSV4 256k Spark4/Spark7 Result

Node and launch:

```text
nodes: spark4 head + spark7 worker, used while spark5 needs physical reset
model: deepseek-ai/DeepSeek-V4-Flash
served model: deepseek-v4-flash
vLLM source: experiencenow-ai/vllm@d240cdbcf3de175be57c108fd9cbfce04009ec29
max_model_len: 262144
max_num_seqs: 2
max_num_batched_tokens: 8192
gpu_memory_utilization: 0.8
kv_cache_dtype: fp8
MTP: deepseek_mtp, 2 speculative tokens
native CPU KV offload: enabled, 8 GiB total
SimpleCPUOffload persistent store: /var/tmp/ds4_hma_store/dsv4/simple_cpu_offload_spark47_256k_mtp_20260527
```

Readiness evidence:

```text
spark4 head service: active after benchmark, RSS about 15.0G, peak 35.8G
spark7 worker service: active after benchmark, RSS about 14.2G, peak 34.6G
spark4 /health: HTTP 200
/v1/models: deepseek-v4-flash, max_model_len=262144
route list: POST /v1/trim_memory present
persistent store size: 2.8G on spark4 and 2.8G on spark7
```

Externally driven replay probe:

```text
prompt_tokens: 6733
cold elapsed: 31.621346s
warm replay elapsed: 3.455483s
speedup: 9.151064x wall-clock
warm external hit log: tokens=6144 raw_tokens=6400 guard_tokens=256
warm prefill compute log: 589 context tokens
external prefix cache hit rate after replay: 45.6%
```

This qualifies the 256k host-local DSV4 lane for live external
SimpleCPUOffload replay speedup. The run did not include a process restart
between cold and replay, so restart-persistent replay remains a separate gate.
`/v1/trim_memory` is installed and callable; the current endpoint reports
successful local prefix reset and `malloc_trim`, while connector-level external
reset/release still returns an explicit unsupported warning for
SimpleCPUOffload.

## Current Safe Claims

```text
Qwen27 APC: proven useful on spark7 for token-identical prefixes
Qwen27 LMCache external KV: not qualified
DSV4 1M launch shape: observed on spark4 during requalification
DSV4 256k host-local source runtime: live on spark4/spark7 with MTP, metrics, prefix caching, SimpleCPUOffload, persistence, and /v1/trim_memory enabled
DSV4 external KV replay speedup: qualified live at 9.15x wall-clock on a 6733-token prefix
DSV4 restart-persistent external KV replay: still pending
```
