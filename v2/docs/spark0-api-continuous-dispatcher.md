# Spark0 API continuous dispatcher

The spark0 coordinator must not run one queued request synchronously inside each HTTP handler. Pipeline services need many concurrent requests in flight so vLLM can batch decode and keep the pipeline filled.

The coordinator starts a background dispatcher by default. HTTP endpoints submit work and, for normal OpenAI/Anthropic-compatible synchronous calls, only wait for the queue result. They do not run queue work scoped to their own `batch_id` while waiting.

Default runtime knobs:

```bash
DS4_API_BACKGROUND_DISPATCH=1
DS4_API_DISPATCH_WINDOW=64
DS4_API_DISPATCH_BATCH_LINGER_S=0.01
DS4_API_DISPATCH_IDLE_SLEEP_S=0.005
DS4_API_DISPATCH_HEARTBEAT_S=2.0
DS4_API_DISPATCH_LEASE_TTL_S=900
DS4_API_TRANSPORT_MAX_ATTEMPTS=3
```

`/ds4/dispatcher/status` reports whether the dispatcher is running and the last queue-work summary. For high-concurrency DSV4 throughput sweeps, set `DS4_API_DISPATCH_WINDOW` to the target in-flight request count.

The dispatcher claims globally across ready work. Compute-domain leases still prevent mixing all-Spark services; while a service owns `spark-fleet-0`, refill prefers that same service until its work drains.

The legacy direct-sync behavior is available only for tests or emergency debugging:

```bash
DS4_API_BACKGROUND_DISPATCH=0
```

In that mode, an HTTP request handler falls back to running queue work for the request's own batch while it waits.

## File-driven throughput runs

Performance runs should be file-driven even when they go through the API. The
request JSONL is the contract for the cohort, and the coordinator API is only
the ingress into the durable queue:

```bash
python3 scripts/ds4_api_queue_benchmark.py \
  --base-url http://127.0.0.1:8700 \
  --model dsv4_flash_pp8 \
  --batch-id dsv4-c256-128x128 \
  --batch-size 256 \
  --concurrency 256 \
  --limit 256 \
  --input-tokens 128 \
  --output-tokens 128 \
  --out-dir /home/spark0/ds4_bench/dsv4-c256-128x128
```

That writes:

```text
requests.jsonl
manifest.json
submit.json
status.json
collect.json
summary.json
```

To replay the exact same cohort after a deployment change:

```bash
python3 scripts/ds4_api_queue_benchmark.py \
  --base-url http://127.0.0.1:8700 \
  --model dsv4_flash_pp8 \
  --batch-id dsv4-c256-128x128-replay \
  --requests-jsonl /home/spark0/ds4_bench/dsv4-c256-128x128/requests.jsonl \
  --concurrency 256 \
  --limit 256 \
  --out-dir /home/spark0/ds4_bench/dsv4-c256-128x128-replay
```

Do not pass `--drive-worker` for production benchmarks. The background
dispatcher must own claiming/refill so compatible requests stay in one model
cohort instead of being split by synchronous caller behavior.
