# Ops: Logging + Metrics Conventions

Goal: make Spark0/Spark1 troubleshooting reproducible and grep-able, with minimal
future refactors.

## Logging

Preferred default: **structured JSONL to journald**.

Recommended common fields:

- `ts` (RFC3339 or unix ns)
- `level` (`debug|info|warn|error`)
- `msg`
- `component` (e.g. `loader`, `scheduler`, `net`, `cuda`)
- `ds4_instance` (`spark0`, `spark1`)
- `rank`, `world_size` (for TP=2)
- `request_id` (stable for a streaming request)

Human runbook:

```bash
journalctl -u ds4@spark0.service --since "1 hour ago" --no-pager
journalctl -u ds4@spark0.service -o json | head
```

If file logs are needed, use `/var/log/ds4/` and ensure log rotation is in
place before a soak test.

## Metrics

Preferred: Prometheus scrape endpoint on each Spark.

Naming:

- Prefix all metrics with `ds4_`
- Use base units (seconds, bytes)
- Avoid high-cardinality labels (no raw prompts, no user IDs)

Recommended baseline metrics:

- `ds4_build_info{git_sha="...",host="..."} 1`
- `ds4_requests_inflight`
- `ds4_request_latency_seconds_bucket` (histogram)
- `ds4_tokens_generated_total`
- `ds4_gpu_utilization_percent` (if sourced from NVML)
- `ds4_cuda_oom_total`

Prometheus scrape snippet example: `deploy/config/prometheus-scrape.ds4.yml.example`.
