# Spark queue runbook

The v2 queue is now the only live DS4 substrate. The Mac Studio can submit and
drain a request while the model call executes on the selected Spark through
SSH:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit \
  --queue-dir /tmp/ds4_v2_queue \
  --profiles-dir profiles/models \
  --topology profiles/topology/static_sparks.json \
  --requests /tmp/requests.jsonl \
  --batch-id smoke-001

PYTHONPATH=src python3 -m ds4_infer.cli queue-work \
  --queue-dir /tmp/ds4_v2_queue \
  --profiles-dir profiles/models \
  --runner spark \
  --limit 1
```

`--runner spark` posts to the selected Spark node's local
`http://127.0.0.1:8000` endpoint by SSH. It tries the unified `/ds4/batches`
surface first and falls back to OpenAI-compatible `/v1/chat/completions` or
`/v1/completions` when the Spark only exposes vLLM.

Manual chat uses the same path:

```bash
ds4-spark-chat -m ds4v
ds4-spark-chat -m qwen
ds4-spark-chat -m ds4a
```

Aliases:

- `ds4v`: DeepSeek V4 Flash vLLM/MTP lane on spark4+spark5.
- `ds4a`: DeepSeek V4 Flash antirez/support profile.
- `qwen`: Qwen efficient lane on spark0-3.
- `fast`: fastest Qwen lane on spark0-3.

The controller keeps the full chat history in the local history file, but each
model request is executed on the Spark selected by the v2 topology.
