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
  --batch-id centaur-run-001 \
  --priority 10
```

Priority is an explicit queueing field. Lower numbers run first. Use normal
priority `10` for background regression queues and priority `1` for experiment
batches that should be claimed as soon as an existing lease window finishes.
Immediate requests still default to priority `0` unless the submitter
explicitly passes another value. The chosen priority is visible in
`queue-submit`, request status, and submitted events.

Each request is resolved to a model profile at submission time. Normal queued
model requests are late-bound to a Spark node when that node worker has room.
The worker prepares requests for its node, then claims the highest-priority
ready requests for one profile/node window. Lower priority numbers run first;
creation time is the tie breaker.

Partial batches use a simple linger timer. If the ready set is smaller than
`--limit`, `queue-worker` waits until no newer ready request has arrived for
`--batch-linger-s`, then dispatches the partial batch instead of waiting
forever.

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

`queue-worker` claims compatible model work for one profile/node window and commits the leases immediately. Batch-capable model runners send one `/ds4/batches` call and persist each returned row separately. Non-batch model runners still finish requests as each future completes, so a fast request can emit its event without waiting for a slow sibling. CPU service jobs use their service batch call.

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

To cancel the remaining queued work in a batch/job:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-cancel \
  --queue-dir /tmp/ds4_queue \
  --job-id centaur-run-001
```

Cancellation is deliberately conservative. It marks `queued` and `ready`
requests as `cancelled`, writes completion notices, and records `cancelled`
events. Running requests are marked `cancel_requested`; their late model result
is ignored when it returns and the request becomes `cancelled`.

Every completed, failed, or cancelled request also writes:

```text
/tmp/ds4_queue/notices/<request_id>.json
```

Centaur can either poll events or watch completion notices.

## KV Readiness

The old prefix-warm sidecar is gone. KV work is part of the queue pipeline:
submission records the cache key and estimated bytes, a node worker binds the
request to its node before readiness, and ready work is claimed only after the
node-local KV reservation succeeds.

```json
{
  "metadata": {
    "kv_cache_key": "sha256:...",
    "kv_bytes_estimate": 123456
  },
  "input": {
    "skeleton_hash": "sha256:...",
    "shared_prefix": "repo skeleton\nrules\noutput contract\n",
    "suffix": "target atom or one question"
  }
}
```

The queue retains completed KV entries as `idle` instead of ejecting them on
completion. If `--kv-capacity-bytes` is set and a new readiness reservation
would exceed the node's cap, the queue deletes least-recently-used idle entries
until the reservation fits. Running or ready KV is never purged to make room;
the worker simply leaves the request queued until capacity opens.

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-work \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --limit 12 \
  --concurrency 12 \
  --max-node-depth 14 \
  --batch-linger-s 0.25 \
  --kv-capacity-bytes 120000000000
```
