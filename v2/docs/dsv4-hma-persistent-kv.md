# DSV4 HMA persistent KV connector

This release treats durable DSV4 KV reuse as a model-specific vLLM connector problem, not as generic LMCache plumbing.

Antirez's DSV4 engine can persist its own DSV4 runtime state because it owns the compressed/sliding/indexer/compressor representation. vLLM does not get that for free by pointing LMCache at the model. The vLLM connector has to know the Hybrid Memory Allocator groups and the DSV4-specific state parts that must survive across requests and process restarts.

## Principle

Centaur and DS4 should never see raw KV tensors. They request inference through DS4 profiles. The Spark/vLLM side owns durable cache mechanics.

The new experimental profile is:

```text
dsv4_vllm_hma_persistent_experimental_v1
model_id: deepseek-ai/DeepSeek-V4-Flash
backend:  vllm_hma
```

It is pinned-only and not production eligible. It exists to let xhigh wire and test the vLLM-side HMA extractor/injector hooks.

## Launch plan

```bash
PYTHONPATH=src python3 -m ds4_hma.cli plan \
  --deployment profiles/hma/dsv4_hma_persistent.json

PYTHONPATH=src python3 -m ds4_hma.cli write-scripts \
  --deployment profiles/hma/dsv4_hma_persistent.json \
  --output-dir /tmp/ds4_hma_dsv4
```

The generated `--kv-transfer-config` uses vLLM dynamic connector loading:

```json
{
  "kv_connector": "DS4HmaPersistentConnector",
  "kv_connector_module_path": "ds4_hma.vllm_connector",
  "kv_role": "kv_both",
  "kv_load_failure_policy": "fail"
}
```

The launch plan also keeps the DSV4 long-context/HMA flags that were live
validated on spark4+spark5:

```text
--max-model-len 1048576
--enable-prefix-caching
--no-disable-hybrid-kv-cache-manager
--kv-cache-dtype fp8
```

The connector extra config declares required state parts:

```text
mla_or_latent_kv
sliding_window_state
indexer_state
compressor_state
hma_group_blocks
```

## Acceptance gate

Do not make this profile a default route until all pass:

```text
1. vLLM imports ds4_hma.vllm_connector.
2. DSV4 starts with the dynamic connector.
3. A warm request writes a ds4-dsv4-hma-state-package-v1 manifest.
4. The vLLM process restarts.
5. The same prefix reloads from disk without hidden recompute.
6. Output matches the non-cache baseline.
7. TTFT/prefill is materially lower than cold baseline.
8. A missing/corrupt package fails visibly because kv_load_failure_policy=fail.
```

The connector currently fails closed at the live extractor/injector seam. That is intentional: a generic tensor-only cache would be worse than no cache for DSV4 because it would silently drop HMA-specific state.
