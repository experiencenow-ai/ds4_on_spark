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

Priority is an explicit queueing field. Lower numbers run first. Use the
default normal priority `10` for background regression queues and `1` for
interactive/experiment batches that should be claimed as soon as an existing
lease finishes. Immediate requests still default to priority `0` unless the
submitter explicitly passes another value. The chosen priority is visible in
`queue-submit`, request status, and submitted events.

Each request is resolved to a model profile and `batch_key` at submission time.
Normal queued model requests are late-bound to a Spark node when a node worker
has an open slot. Immediate requests may still bind to a node at submission
time. The `batch_key` includes:

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

`queue-worker` claims compatible model work for one profile/node window and commits the leases immediately. Batch-capable model runners dispatch each claim independently, so a fast request can finish, emit an event, and write its notice without waiting for the slowest request in the window. CPU service jobs still use their service batch call.

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
  --topology profiles/topology/static_sparks.json \
  --runner spark \
  --node-id spark0 \
  --min-group-size 2 \
  --max-output-tokens 1
```

For repeated regression/evolution runs where a request may land on any resident
node for the same profile, warm every resident node for the active work window
explicitly:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-warm-prefixes \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --runner spark \
  --all-resident-nodes \
  --min-group-size 1 \
  --concurrency 16 \
  --max-output-tokens 1
```

After the first active window is resident, keep warming just ahead of workers
instead of replaying the whole window. Caps are applied after already-warm
prefixes are skipped, so repeated calls advance to the next cold prefix groups:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-warm-prefixes \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --min-group-size 1 \
  --max-groups 2 \
  --concurrency 2 \
  --max-output-tokens 1 \
  --loop \
  --sleep-s 0.25
```

Workers can also warm just before claiming requests:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-work \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --node-id spark0 \
  --warm-prefixes \
  --warm-max-groups 2 \
  --limit 128
```

This sends one tiny synthetic request per `(node, profile, chat mode,
skeleton_hash, shared_prefix)` group. The shared prefix is byte-identical to the
real request prefix, so vLLM Automatic Prefix Caching can reuse prefill work.
The queue records best-effort status in `prefix_warms`; it cannot prove vLLM has
not evicted the blocks later.

Disk `kv_cache_ref` prefix blobs are durable prefix text, not proof that decoded
KV blocks are resident. Use them to rebuild and warm the active window; do not
assume the whole benchmark is resident in unified memory unless the serving
backend exposes a fail-closed disk-KV load contract.

For decoded external KV, use `input.kv_cache` from `docs/kv-cache-api.md`.
`queue-submit` validates it into `input.kv_cache_plan`, and the queue includes
the plan hash in the batch key so different cache sources cannot be grouped as
if they were the same resident prefix.

Status:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-prefix-status \
  --queue-dir /tmp/ds4_queue \
  --skeleton-hash sha256:...
```
