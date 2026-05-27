# Spark queue runbook

The v2 queue is now the only live DS4 substrate. The durable queue should run
on one coordinator first, normally `spark0`. The current implementation uses a
local SQLite queue, so workers that claim from that queue should run on the
coordinator host.

The Mac Studio can submit requests while model calls execute on the selected
Spark:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit \
  --queue-dir /tmp/ds4_v2_queue \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests /tmp/requests.jsonl \
  --batch-id smoke-001

PYTHONPATH=src python3 -m ds4_infer.cli queue-worker \
  --queue-dir /tmp/ds4_v2_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark4+spark5 \
  --limit 16 \
  --concurrency 8 \
  --loop
```

`queue-worker` claims a compatible `batch_key`, commits the lease immediately,
then sends the compatible group through one batch-capable runner call. The
Spark runner posts one `/ds4/batches` payload with multiple items when the
worker claims multiple same-shape model requests.

## Qwen Throughput Policy

Qwen27 throughput must be measured as separate service metrics:

| Metric | Current policy value |
|---|---:|
| `prefill_prompt_tok_s` | ~7,660 prompt tok/s per Spark |
| `single_stream_decode_tok_s` | ~8 generated tok/s |
| `aggregate_decode_tok_s_at_16` | ~99 generated tok/s per Spark |
| `aggregate_decode_tok_s_at_32` | historical calibration only, not a launch cap |

The `measured_output_tps` profile field is aggregate batched decode, not
single-request chat latency. A one-off long answer can take minutes even on a
warm lane; Qwen27 launches should stay capped at `max_num_seqs=12` unless a new
live calibration updates the runtime contract. Comparing single-stream latency
to aggregate batched throughput is invalid for capacity planning.

`--runner spark` SSHes to the selected Spark and posts to that Spark's local
`http://127.0.0.1:8000` DS4 endpoint. The Spark runner uses `/ds4/batches`;
legacy `/v1/*` endpoints are not part of readiness or production routing.

Recommended first deployment:

```text
spark0 process 1: --node-id spark0
spark0 process 2: --node-id spark1
spark0 process 3: --node-id spark2
spark0 process 4: --node-id spark3
spark0 process 5: --node-id spark4+spark5
spark0 process 6: --node-id spark6
```

This covers the seven production GPUs: spark0-3 and spark6 as independent
Qwen lanes, and spark4+spark5 as one DSV4 group lane.
spark7 remains experimental unless the topology explicitly assigns it a
resident production profile.

The current DSV4 group ingress is spark5:

```bash
export DS4_SPARK_NODE_MAP_JSON='{"spark4+spark5":"spark5"}'
```

Resident workers on every Spark are the next shape, but they need a shared
lease authority, for example a small coordinator HTTP API on spark0. Do not
make every Spark independently route global work from separate local SQLite
queues; that creates split-brain scheduling.

## Saturation Test

From the Mac Studio, after the LLM gateways have been restarted and `/ds4/status`
is healthy on the production lanes:

```bash
PYTHONPATH=src scripts/ds4_queue_saturation.py
```

The harness keeps the topology-derived mix queued for five minutes:

```text
spark0-3: qwen3_6_27b_fp8_efficient_v1
spark0-3: qwen3_6_35b_a3b_fp8_fastest_v1
spark4+spark5: dsv4_vllm_mtp_smartest_v1, ingress spark5
spark6: qwen3_6_27b_fp8_efficient_v1, qwen3_6_35b_a3b_fp8_fastest_v1
```

It writes `plan.json`, `gpu_samples.jsonl`, `summary.json`, and the queue DB
under `/tmp/ds4_queue_saturation_<run_id>/`. The run passes only if the queue
drains, no request fails, and every production GPU records the required active
seconds above the configured threshold.

For throughput tuning, run a stress ladder:

```bash
PYTHONPATH=src scripts/ds4_queue_saturation.py \
  --stress-ladder 1x1,2x2,4x4,8x8 \
  --duration-s 180 \
  --required-active-s 120
```

Each phase writes its own `summary.json`; the suite writes
`stress_summary.json` with the load point that maximized aggregate completion
tok/sec. Every GPU sample includes `gpu_nodes` plus a same-order
`gpu_util_vector`, so the best throughput point can be compared directly
against the 7x Spark utilization vector.

Manual chat uses the same path:

```bash
ds4-spark-chat -m ds4v
ds4-spark-chat -m qwen
ds4-spark-chat -m fast
```

Aliases:

- `ds4v`: DeepSeek V4 Flash vLLM/MTP lane on spark4+spark5.
- `qwen`: Qwen efficient lane on spark0-3 and spark6.
- `fast`: fastest Qwen lane on spark0-3 and spark6.

The controller keeps the full chat history in the local history file, but each
model request is executed on the Spark selected by the v2 topology.

CPU utility work should also enter through the durable queue when it needs
batching, leases, status, or completion notices:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit-cpu \
  --queue-dir /tmp/ds4_v2_queue \
  --service text_metrics \
  --items /tmp/cpu_items.jsonl
```
