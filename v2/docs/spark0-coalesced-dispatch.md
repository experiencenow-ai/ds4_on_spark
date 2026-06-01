# Spark0 coalesced dispatch

The spark0 API must not feed resident PP services as hundreds of independent
one-request HTTP calls. That creates staggered prefill cohorts, and vLLM then
carries those fragmented microbatches through decode.

The coordinator has two batching layers:

1. The background dispatcher claims a compatible cohort from the DS4 queue and
   submits that cohort as one dispatcher future.
2. For compatible completion requests, the pipeline runner sends one OpenAI
   `/v1/completions` request with `prompt: [...]` instead of one HTTP request
   per item.

This keeps the public API OpenAI-compatible while making vLLM see the entire
cohort before prefill.

## Throughput benchmark knobs

For a forced c256 run through spark0, use a large dispatcher window and a large
refill batch. The topology max batch can be overridden without editing the JSON
topology.

```bash
export DS4_API_BACKGROUND_DISPATCH=1
export DS4_API_DISPATCH_WINDOW=256
export DS4_API_DISPATCH_REFILL_BATCH=256
export DS4_API_DISPATCH_BATCH_LINGER_S=0.25
export DS4_API_BATCH_LIMITS_JSON='{"qwen27_bf16_pp8":256,"dsv4_flash_pp8":256}'
export DS4_PIPELINE_COHORT_COMPLETIONS=1
export DS4_PIPELINE_COMPLETION_COHORT_MAX=512
```

`DS4_API_DISPATCH_BATCH_LINGER_S` is deliberately larger for benchmarks than for
latency-sensitive service. It gives concurrent HTTP clients time to arrive
before the first prefill is dispatched.

## Preferred benchmark submission

The cleanest OpenAI-compatible benchmark is a single `/v1/completions` request
with an array of prompts:

```json
{
  "model": "qwen27_bf16_pp8",
  "prompt": ["prompt 0", "prompt 1", "prompt 2"],
  "max_tokens": 256,
  "temperature": 0,
  "extra_body": {"ignore_eos": true}
}
```

The coordinator expands this into one DS4 batch and returns an OpenAI-style
response with one `choices[]` entry per prompt. Internally, the dispatcher
should claim the whole batch as one compatible cohort and the runner should send
one vLLM `/v1/completions` request with `prompt: [...]`.

## What to verify in logs

During the benchmark, verify:

```text
spark0 dispatcher last_claimed_cohort_size ~= requested concurrency
spark0 dispatcher pending_cohorts stays low
runner transport coalesced_completion_batch=true
vLLM prefill does not show 1 + 20 + 123 + 112 style fragmentation for one c256 cohort
```

If vLLM still sees split prefill groups, increase linger slightly or use
prompt-array submission instead of many independent HTTP requests.

## Production defaults

For production, the same path stays enabled, but the window and linger can be
smaller:

```bash
export DS4_API_DISPATCH_WINDOW=64
export DS4_API_DISPATCH_REFILL_BATCH=16
export DS4_API_DISPATCH_BATCH_LINGER_S=0.02
```

The benchmark knobs are for measuring saturated PP throughput, not for every
low-latency request.
