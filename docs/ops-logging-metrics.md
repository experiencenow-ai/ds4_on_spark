# Ops: Logging + Metrics Conventions

Goal: make Spark troubleshooting reproducible and grep-able, with minimal
future refactors.

## Logging

Preferred default: **structured JSONL to journald**.

Recommended common fields:

- `ts` (RFC3339 or unix ns)
- `level` (`debug|info|warn|error`)
- `msg`
- `component` (e.g. `loader`, `scheduler`, `net`, `cuda`)
- `ds4_instance` (`spark0`, `spark1`, `spark2`, `spark3`)
- `rank`, `world_size` (for TP=2 / TP=4)
- `request_id` (stable for a streaming request)

Human runbook:

```bash
journalctl -u ds4@spark0.service --since "1 hour ago" --no-pager
journalctl -t ds4-spark0 -n 200 --no-pager
journalctl -u ds4@spark0.service -o json | head
```

If you need to capture a repeatable snapshot for debugging (systemd + journald + routing + key DS4 env fields), use the support bundle script:

- `docs/ops-support-bundle.md`

If you want a lightweight, repeatable **run log** (recommended), use the Mac-side snapshot helper and follow the run note hygiene guidance:

- `docs/ops-run-notes.md`

If file logs are needed, use `/var/log/ds4/` and ensure log rotation is in
place before a soak test. Example: `deploy/config/logrotate.ds4.conf.example`.

### Journald Persistence (Optional)

For early bring-up it can be useful to persist journal logs across reboots.

This repo includes an example drop-in:

- `deploy/config/journald.ds4.conf.example`

Apply only with human approval and after reviewing `man journald.conf` on the
target OS.

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
Prometheus alerting rules example: `deploy/config/prometheus-alerts.ds4.yml.example`.

## Spark (Optional)

If Spark is managed via systemd (see `docs/deployment-spark-standalone-systemd.md`), prefer journald for unit logs:

```bash
journalctl -u spark-master@spark0.service -n 200 --no-pager
journalctl -u spark-worker@spark1.service -n 200 --no-pager
journalctl -t spark-master-spark0 -n 200 --no-pager
journalctl -t spark-worker-spark1 -n 200 --no-pager
```

For troubleshooting distributed runs, also consider enabling Spark event logs and recording the event log directory in your run notes.
