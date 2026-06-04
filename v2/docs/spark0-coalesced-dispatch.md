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

## Resident64 benchmark knobs

For the stable resident DSV4 profile, feed enough work to keep PP8 busy without
using the old max-KV shape.
The source of truth is
`profiles/production/dsv4_flash_pp8_resident64.json`; these shell variables are
the materialized values that the relaunch/audit path verifies.

```bash
export DS4_API_BACKGROUND_DISPATCH=1
export DS4_API_DISPATCH_WINDOW=64
export DS4_API_DISPATCH_REFILL_BATCH=64
export DS4_API_DISPATCH_BATCH_LINGER_S=0.05
export DS4_API_BATCH_LIMITS_JSON='{"qwen27_bf16_pp8":12,"dsv4_flash_pp8":64}'
export DS4_PIPELINE_COHORT_COMPLETIONS=1
export DS4_PIPELINE_COMPLETION_COHORT_MAX=64
export DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET=16384
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
bounded vLLM `/v1/completions` requests with `prompt: [...]`. The API-level
batch can be larger than a single vLLM prompt-array post: the runner splits it
by `DS4_PIPELINE_COMPLETION_COHORT_MAX` and
`DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET`.

## What to verify in logs

During the benchmark, verify:

```text
spark0 dispatcher last_claimed_cohort_size ~= requested concurrency
spark0 dispatcher pending_cohorts stays low
runner transport coalesced_completion_batch=true
vLLM prefill does not show 1 + 20 + 43 style fragmentation for one c64 cohort
```

If vLLM still sees split prefill groups, increase linger slightly or use
prompt-array submission instead of many independent HTTP requests. If vLLM
admits hundreds of requests and stops making progress, lower
`DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET`; the large API batch should stay
queued on spark0 rather than entering vLLM as one oversized prompt-array post.

## Production defaults

For production, the same path stays enabled, but the window and linger can be
smaller:

```bash
export DS4_API_DISPATCH_WINDOW=64
export DS4_API_DISPATCH_REFILL_BATCH=64
export DS4_API_DISPATCH_BATCH_LINGER_S=0.05
```

The benchmark knobs are for measuring saturated PP throughput, not for every
low-latency request.
