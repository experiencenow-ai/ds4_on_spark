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
