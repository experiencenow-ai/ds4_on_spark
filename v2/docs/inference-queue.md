# Inference Queue

Centaur should think in individual requests. The inference service may batch internally, but every request must have its own status, completion notice, and pollable event stream.

The current queue is SQLite-backed with WAL enabled. It is intentionally simple enough to run on one Spark controller host while still supporting independent request completion.

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

## Work

A resident Spark worker should normally claim only its own node:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-work \
  --queue-dir /tmp/ds4_queue \
  --profiles-dir profiles/models \
  --runner fake \
  --node-id spark0 \
  --limit 16
```

A real runner later replaces `--runner fake`. The queue contract does not change.

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

Every completed or failed request also writes:

```text
/tmp/ds4_queue/notices/<request_id>.json
```

Centaur can either poll events or watch completion notices.
