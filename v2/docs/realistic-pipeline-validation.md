# Realistic Pipeline Validation

This runbook is for validating resident Spark pipelines through the spark0 API.
It deliberately avoids direct model-port shortcuts.

## Required Gates

Before relaunch or benchmark:

```bash
cd /home/spark0/ds4_on_spark/v2
PYTHONPATH=src python3 scripts/ds4_pipeline_runtime_audit.py
```

The audit must pass. It checks that:

- DSV4 topology, runtime contract, and KV deployment agree on `max_num_seqs`,
  `max_num_batched_tokens`, KV bytes, and layer partition.
- DSV4 uses the native auto backend selection, not forced DeepGEMM or Marlin.
- Qwen production profiles use explicit FP8 KV and Triton attention.
- Qwen production profiles keep vLLM async scheduling disabled.
- Coordinator relaunch uses a bounded coalesced token budget and a compute
  lease quantum.
- Dispatcher KV admission is bounded instead of unlimited.

## Coordinator Relaunch

Use the repo-owned relaunch script:

```bash
cd /home/spark0/ds4_on_spark/v2
python3 scripts/ds4_relaunch_coordinator_api.py --profile throughput
```

The throughput profile intentionally uses:

```text
DS4_PIPELINE_COMPLETION_COHORT_TOKEN_BUDGET=262144
DS4_API_BATCH_LIMITS_JSON includes dsv4_flash_pp8=512
DS4_COMPUTE_LEASE_QUANTUM_S=180
DS4_API_DISPATCH_KV_CAPACITY_BYTES=51539607552
```

The token budget is an API-side cohort guard so realistic long prompts split
before vLLM sees an oversized prompt array.
The KV capacity is a per-node/per-shard admission guard. Set it explicitly for
realistic profiles; `0` is accepted only for deliberate debug runs and is
reported as `kv_admission_warning=unlimited_kv_admission` in dispatcher status.

The current DSV4 PP8 production launch profile is bounded, not max-KV:

```text
--max-num-seqs 64
--max-num-batched-tokens 32768
--kv-cache-memory-bytes 8589934592
--gpu-memory-utilization 0.35
```

Use this as the default smoke/performance envelope before considering larger
DSV4-only runs.

## Telemetry Bridge

The Mac telemetry collector is the source of truth. From the Mac checkout,
bridge its summary into the coordinator/UI with:

```bash
cd /Users/mac/Documents/New\ project\ 4/v2
PYTHONPATH=src python3 scripts/ds4_post_cluster_telemetry.py \
  --summary-json /tmp/ds4_telemetry/mac/cluster_summary.json \
  --service-id dsv4_flash_pp8
```

Use `--dry-run` to inspect the report without posting.

## Mixed-Shape API Benchmark

From the Mac checkout, generate a file-driven mixed-shape benchmark:

```bash
cd /Users/mac/Documents/New\ project\ 4/v2
PYTHONPATH=src python3 scripts/ds4_api_queue_benchmark.py \
  --model dsv4 \
  --batch-size 1 \
  --shape-mix-json '[{"count":128,"input_tokens":256,"output_tokens":128},{"count":64,"input_tokens":2048,"output_tokens":128},{"count":32,"input_tokens":8192,"output_tokens":256}]' \
  --concurrency 224 \
  --limit 224 \
  --out-dir /private/tmp/ds4_realistic_dsv4 \
  --write-only
```

Then submit the generated JSONL by removing `--write-only`. Benchmarks cancel
their batch on timeout by default; use `--no-cancel-on-timeout` only for
debugging.

## Chat Fast Path

The coordinator does not invent chat templates. Chat requests coalesce into the
completion prompt-array fast path only when the queue request already includes a
canonical rendered prompt:

```json
{
  "chat": true,
  "input": {
    "rendered_prompt": "..."
  }
}
```

Unrendered chat remains valid, but it is not counted as a prompt-array fast-path
benchmark unless each result transport has:

```text
coalesced_completion_batch=true
```

Rendered-chat coalescing also marks:

```text
coalesced_rendered_chat_completion_batch=true
```

## Streaming

`/v1/completions` with `stream=true` stays on the queue path. vLLM SSE token
deltas are forwarded as request-scoped queue `delta` events and then emitted to
the caller as OpenAI text-completion chunks. Terminal chunks carry usage and an
empty text body when deltas were already streamed for that request.

Chat streaming remains disabled unless the chat request is first converted into
a canonical rendered-prompt completion request.

## Qwen Baseline

All Qwen production launches must show:

```text
--kv-cache-dtype fp8
--attention-backend TRITON_ATTN
--no-async-scheduling
```

Do not compare against old Qwen cache directories that lack the `fp8kv`
namespace.
