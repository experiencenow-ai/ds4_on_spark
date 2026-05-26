# Model gateway operational notes from v1

These are the useful PR #1402 details that should survive the v1 purge. They
are operational contracts, not a request to revive the monolithic lazy proxy.

## Gateway inventory

The old gateway supported four backend classes:

- `vllm_lazy_hf`: discover Hugging Face model directories and start vLLM on demand.
- `vllm_remote`: forward selected model IDs to a remote vLLM endpoint.
- `ds4_server`: serve GGUF models, including the DeepSeek V4 Flash MTP sidecar when present.
- `llama_server`: serve explicit JSON model specs through llama.cpp compatible server binaries.

The v2 runtime should keep these as profile/backend concepts. The Spark runner
uses the Spark-local `/ds4/batches` endpoint, so model execution stays on the
Spark rather than the Mac Studio controller.

## Useful endpoint contracts

The v1 operational surface included both legacy compatibility endpoints and
DS4 endpoints. The v2 production contract is the DS4 surface.

- `/ds4/status`
- `/ds4/gpu`
- `/ds4/models` or `/ds4/profiles`
- `/ds4/services`
- `/ds4/batches`
- `/ds4/cpu/batches`
- `/ds4/release`

In v2, model and CPU batches both enter the durable `ds4_infer.queue` when they
need leases, status, polling, or completion notices. Model execution is handled
by the Spark runner; CPU service execution is handled by `ds4_tools.cpu_batch`.
GPU/status endpoints are Spark-local service concerns and should be exposed by
SparkRunner or the gateway process on each Spark, not by the Mac controller.

## Startup resident loading

The v2 way to make reboots boring is topology-driven warmup, not a hard-coded
fleet script. Install `v2/deploy/systemd-user/ds4-startup-models.service` on
each Spark with `DS4_NODE_ID` set to that Spark's topology ID, or leave it as
`%H` when hostnames are `spark0` through `spark7`.

At boot the service runs:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli startup-models \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --node-id "$DS4_NODE_ID"
```

That posts one tiny request per resident profile to the Spark-local
OpenAI-compatible endpoint. It warms spark0-3 and spark6 Qwen profiles plus
spark4's grouped DSV4 vLLM/MTP lane. Spark5 is a grouped-lane secondary and
spark7 is experimental/on-demand, so neither gets a production warmup request.

## Tuning defaults worth preserving

The old GB10/Spark vLLM defaults were selected for throughput:

- `--max-num-seqs 64`
- `--max-num-batched-tokens 32768`
- `--gpu-memory-utilization 0.75`
- `--enable-chunked-prefill`
- `--enable-prefix-caching`
- `--async-scheduling`

The DeepSeek V4 Flash path also carried parser/backend details:

- Qwen3 reasoning parser support for Qwen-family models.
- Code/GLM/Phi parser mapping when the model config advertises those families.
- DeepSeek V4 HF path using FP8 KV.
- DFlash drafter discovery under `DS4_DFLASH_ROOT`.
- DFlash speculative config: `method=dflash`, `num_speculative_tokens=15`,
  FlashAttention backend, max seqs 16, GPU utilization 0.85.
- `DS4_GATEWAY_TUNING_JSON` and `DS4_GATEWAY_TUNING_FILE` to override per-model
  effective tuning, reported back through status.

## Batch semantics

The model batch API enforced:

- One model per batch.
- Ordered results.
- Streaming forced off.
- `BATCH_MAX_ITEMS`, `BATCH_MAX_CONCURRENCY`, and `BATCH_DEFAULT_CONCURRENCY`
  bounds.

The CPU batch API enforced:

- Process-wide bounded worker pool.
- Ordered results with `custom_id` passthrough.
- `CPU_SERVICE_MAX_ITEMS`, `CPU_SERVICE_MAX_CONCURRENCY`, and
  `CPU_SERVICE_DEFAULT_CONCURRENCY` bounds.
- Bounded text payloads and allowlisted local command execution only.

The v2 CPU implementation is `ds4_tools.cpu_batch`; the registry entry is
`tool:ds4.cpu.batch`, and durable queued submission uses `queue-submit-cpu`.
