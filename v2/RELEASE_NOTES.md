# ds4_on_spark v2 queue + transfer release

This release keeps the purge architecture and adds the service pieces needed for stable Centaur use:

- spark6 is now the fifth resident Qwen lane.
- Qwen production capacity is exactly 5 resident lanes: spark0, spark1, spark2, spark3, and spark6.
- The antirez DSV4 profile remains in the registry as a non-production legacy fallback, but it is no longer a resident static lane.
- The inference queue is request-first: every request has independent status, completion notice, and pollable events.
- Queue batch keys include profile, node, chat/completion mode, job class, input size, output size, thinking budget, and shared prefix hash.
- `ds4-transfer` adds a direct Spark-to-Spark transfer planner/executor for the 200Gbps fabric.
- `ds4-kvcache` plans optional vLLM external KV cache deployments without creating new model profiles.

## Static topology

```text
spark0-3,6: Qwen 27B/fastest-Qwen resident lanes
spark4-5: DSV4 vLLM/MTP resident lane
spark6:   Qwen 27B/fastest-Qwen resident lane
spark7:   experimental on-demand lane
```

## Queue commands

```bash
PYTHONPATH=src python3 -m ds4_infer.cli queue-submit --queue-dir /tmp/q --profiles-dir profiles/models --topology profiles/topology/static_sparks.json --requests requests.jsonl
PYTHONPATH=src python3 -m ds4_infer.cli queue-status --queue-dir /tmp/q --request-id req-1
PYTHONPATH=src python3 -m ds4_infer.cli queue-poll --queue-dir /tmp/q --after-event-id 0
PYTHONPATH=src python3 -m ds4_infer.cli queue-work --queue-dir /tmp/q --profiles-dir profiles/models --runner fake --node-id spark0 --limit 16
```

## Transfer command

```bash
PYTHONPATH=src python3 -m ds4_transfer.cli plan \
  --topology profiles/transfer/spark_200g.json \
  --request-json '{"format":"ds4-transfer-request-v1","source_node":"spark0","source_path":"/mnt/data/run/","destination_node":"spark4","destination_path":"/mnt/data/run/"}'
```

## Validation

```bash
python3 -m compileall -q src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Result: 85 tests passed.

## Additional runner/tool/chat update

- `dsv4_vllm_mtp_smartest_v1` capacity is now 1 grouped lane, assigned to `spark4+spark5`, because the vLLM/MTP profile consumes both Sparks.
- Added best-effort live runners: `vllm`, `antirez`, and `auto` for `ds4-infer submit` and `queue-work`.
- Added `tool:web.fetch`, backed by Playwright rendering when installed and plain HTML fetch otherwise.
- Added `tool:spark.status`, `tool:spark7.command.run`, and transfer tool entries in the lattice registry.
- Added `ds4-spark-chat`, a simple CLI chat interface for the resident vLLM/MTP lane with optional spark7 tool access.
- Added `docs/xhigh-live-validation.md` and `profiles/validation/xhigh_live_validation_tasks.json` for the required live v2 runner checks.
- Added `docs/kv-cache.md` and `profiles/kv_cache/dsv4_spark45_lmcache.json` as optional cache launch plumbing for the existing DSV4 profile.
- Documented live prefix-cache behavior: a spark7 Qwen27 30k-token prompt dropped from 46.190s cold to 0.286s warm, with 29,792 prompt tokens served from local cache.
- Documented context limits: Qwen tokenizer limit is 262,144 tokens; DSV4 model limit is 1,048,576 tokens; current DSV4 service exposes about 3.2M aggregate KV-token slots.
