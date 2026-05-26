# Inference Queue

Centaur should think in individual requests. The inference service may batch internally, but every request must have its own status, completion notice, and pollable event stream.

The current queue is SQLite-backed with WAL enabled. It is intentionally simple enough to run on one Spark coordinator host while still supporting independent request completion.

First production shape:

```text
Centaur/Mac client -> spark0 queue DB + worker processes -> selected Spark local model API
```

Run the durable queue on one coordinator first, normally `spark0`. Start one
or more worker processes on that coordinator and pin each worker with
`--node-id` so it only claims requests assigned to that lane. With
`--runner spark`, the model call still executes on the selected Spark over SSH.

Resident workers on every Spark are the right later shape, but they need a
shared lease authority such as a small coordinator HTTP API. Do not point
independent local SQLite queues on every Spark at the same logical workload.

## Submit

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests requests.jsonl \
  --batch-id centaur-run-001
```

Each request is resolved to a model profile, Spark node, and `batch_key` at submission time. The `batch_key` includes:

```text
node
profile
chat/completion mode
job class
input size bucket
output size bucket
thinking budget bucket
shared prefix hash
immediate/queued class
```

This lets workers process shape-compatible groups without making Centaur know optimal batch sizes.

## Request Identity and Routing

Do not dedupe by prompt, payload hash, or model input. The caller owns request
identity. If the Mac submits the same payload as N distinct request envelopes,
the cluster must produce N LLM calls.

The Spark that receives an envelope is only the ingress. It uses the current
cluster view to choose the destination Spark for the selected model/profile. If
spark3 receives an antirez request, spark3 forwards or records it for the
antirez-capable destination; the destination queue owns that one local job and
emits status for it.

## Work

A resident Spark worker should normally claim only its own node:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-worker \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --limit 16 \
  --concurrency 8 \
  --loop
```

`queue-worker` claims one shape-compatible `batch_key` and commits the claim immediately. Batch-capable runners send the claimed group as one `/ds4/batches` call with the requested concurrency; non-batch test runners keep the per-request fallback used by local tests.

CPU services use the same durable queue:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit-cpu \
  --queue-dir /tmp/ds4_queue \
  --service text_metrics \
  --items cpu_items.jsonl \
  --batch-id cpu-run-001
```

Each claimed request has a lease:

```text
lease_id
leased_by
lease_expires_at
heartbeat_at
attempt_count
```

Pending in-flight requests are heartbeated while the worker waits. Expired leases can be requeued or failed after the attempt budget:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-reap-leases \
  --queue-dir /tmp/ds4_queue \
  --max-attempts 3
```

## Status and polling

Request status:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-status \
  --queue-dir /tmp/ds4_queue \
  --request-id req-001
```

Batch status:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-status \
  --queue-dir /tmp/ds4_queue \
  --batch-id centaur-run-001
```

Event polling:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-poll \
  --queue-dir /tmp/ds4_queue \
  --after-event-id 0
```

## Cancel

Queued requests can be cancelled before a worker claims them:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-cancel \
  --queue-dir /tmp/ds4_queue \
  --request-id req-001 \
  --reason 'superseded by a newer run'
```

To cancel the remaining queued work in a batch:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-cancel \
  --queue-dir /tmp/ds4_queue \
  --batch-id centaur-run-001
```

Cancellation is deliberately conservative. It only marks requests still in
`queued` state as `cancelled`, writes a completion notice, and records a
`cancelled` event. Requests already `running`, `completed`, `failed`, or
`cancelled` are reported in `skipped_state_counts`; the queue does not pretend
to abort an in-flight model call.

Every completed, failed, or cancelled request also writes:

```text
/tmp/ds4_queue/notices/<request_id>.json
```

Centaur can either poll events or watch completion notices.

## Prefix cache warming

For lattice or LongMem batches, put the stable text first:

```json
{
  "input": {
    "skeleton_hash": "sha256:...",
    "shared_prefix": "repo skeleton\nrules\noutput contract\n",
    "suffix": "target atom or one question"
  }
}
```

Then warm groups before normal work:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-warm-prefixes \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --min-group-size 2 \
  --max-output-tokens 1
```

Workers can also warm just before claiming requests:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-work \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --warm-prefixes \
  --limit 128
```

This sends one tiny synthetic request per `(node, profile, chat mode,
skeleton_hash, shared_prefix)` group. The shared prefix is byte-identical to the
real request prefix, so vLLM Automatic Prefix Caching can reuse prefill work.
The queue records best-effort status in `prefix_warms`; it cannot prove vLLM has
not evicted the blocks later.

Status:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-prefix-status \
  --queue-dir /tmp/ds4_queue \
  --skeleton-hash sha256:...
```
