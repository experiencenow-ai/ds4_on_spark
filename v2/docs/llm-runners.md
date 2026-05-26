# LLM runners

The live inference runners are intentionally thin adapters behind the DS4 request contract.

## Runner choices

```bash
ds4-infer queue-worker --runner spark --node-id spark0 --concurrency 8 ...
ds4-infer queue-worker --runner auto --concurrency 8 ...
ds4-infer queue-worker --runner vllm --concurrency 8 ...
ds4-infer queue-worker --runner antirez --concurrency 8 ...
ds4-infer queue-worker --runner fake --concurrency 8 ...
ds4-infer queue-worker --runner command --command ./adapter ...
```

The production cluster path is `SparkHttpRunner`, which requires the
queue-selected Spark node and uses `/ds4/batches` on that Spark. Direct live
`submit --run` execution is intentionally removed; live work goes through
`queue-submit` plus `queue-worker`.

- `fake` is for tests and dry runs.
- `command` is for fixed local adapter commands.
- `spark` is the production Spark gateway runner and fails closed without a selected node.
- `vllm` uses a local OpenAI-compatible vLLM endpoint from `DS4_VLLM_BASE_URL` or `DS4_VLLM_MTP_BASE_URL`. LMCache is a server launch property, not a different client API.
- `antirez` uses the antirez completion endpoint from `DS4_ANTIREZ_BASE_URL`.
- `auto` routes by profile backend: `vllm`, `vllm_mtp`, or `antirez`.

The xhigh should set the endpoint environment on each resident lane:

```bash
export DS4_SPARK_HTTP_BASE_URL=http://127.0.0.1:8000
```

For the current spark4+spark5 DSV4 group, route the logical group to the live
ingress:

```bash
export DS4_SPARK_NODE_MAP_JSON='{"spark4+spark5":"spark5"}'
```
