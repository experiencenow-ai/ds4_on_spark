# Spark trim-memory API

Use this API for client-level memory relief. Do not build raw per-Spark curl
commands in clients.

The stable tool entrypoint is:

```bash
PYTHONPATH=src python3 -m ds4_tools.cli invoke \
  --registry tools/registry.jsonl \
  --tool-id tool:spark.trim_memory \
  --arguments '{"node":"spark0","execute":true}'
```

The operator CLI uses the same control path:

```bash
PYTHONPATH=src python3 -m ds4_infer.cli trim-spark-memory \
  --node-id spark0 \
  --execute
```

The request names the Spark to relieve. The control layer resolves the
topology, the node's trim-default profile, the profile runtime contract, and
the Spark-local vLLM endpoint. The returned payload includes both `node_id` and
`ingress_node_id` so grouped lanes are visible.

## Modes

`mode=abort` is the default emergency mode. vLLM pauses generation, blocks new
work, aborts in-flight requests at the scheduler boundary, resets local prefix
state, asks connector-managed caches to reset when the runtime supports that
hook, trims allocators, and resumes generation. A running CUDA kernel is not
interrupted mid-kernel; the abort is handled when the engine reaches its next
safe scheduling point.

`mode=wait` is the graceful mode. vLLM pauses new work, lets current requests
finish, then performs the same trim. Use it for planned maintenance. Use
`abort` for watchdog or swap-pressure recovery where preserving current
requests matters less than keeping the Spark alive. Runtimes without a direct
SimpleCPUOffload release hook return `status: ok` with a warning instead of
failing the control path after the abort/local-reset step.

## Exact Resolutions

Current production defaults:

```text
spark0 -> qwen3_6_27b_fp8_efficient_v1 -> qwen27_vllm_trim_v1 -> spark0:18100
spark1 -> qwen3_6_27b_fp8_efficient_v1 -> qwen27_vllm_trim_v1 -> spark1:18100
spark2 -> qwen3_6_27b_fp8_efficient_v1 -> qwen27_vllm_trim_v1 -> spark2:18100
spark3 -> qwen3_6_27b_fp8_efficient_v1 -> qwen27_vllm_trim_v1 -> spark3:18100
spark4 -> dsv4_vllm_mtp_smartest_v1 -> dsv4_spark45_vllm_mtp_v1 -> spark4:8000
spark5 -> dsv4_vllm_mtp_smartest_v1 -> dsv4_spark45_vllm_mtp_v1 -> spark4:8000
spark6 -> qwen3_6_27b_fp8_efficient_v1 -> qwen27_vllm_trim_v1 -> spark6:18100
```

Spark7 is experimental and has no resident trim default. Name the running
profile or pass a base URL:

```bash
PYTHONPATH=src python3 -m ds4_tools.cli invoke \
  --registry tools/registry.jsonl \
  --tool-id tool:spark.trim_memory \
  --arguments '{"node":"spark7","profile_id":"qwen3_6_27b_fp8_efficient_v1","execute":true}'
```

The Qwen27 runtime contract maps the Spark7 verification profile to
`http://127.0.0.1:18110`; production Qwen resident lanes use
`http://127.0.0.1:18100`.

Non-default profiles use the same API, but they must have a checked-in runtime
contract or an explicit `base_url`. A profile without a runtime contract fails
before it touches the node; this is intentional so clients do not silently hit
the wrong vLLM process.

## Response Shape

Plan-only calls return:

```json
{
  "format": "ds4-spark-trim-memory-plan-v1",
  "execute": false,
  "node_id": "spark5",
  "ingress_node_id": "spark4",
  "profile_id": "dsv4_vllm_mtp_smartest_v1",
  "runtime_contract_id": "dsv4_spark45_vllm_mtp_v1",
  "endpoint": {
    "method": "POST",
    "base_url": "http://127.0.0.1:8000",
    "path": "/v1/trim_memory",
    "query": "mode=abort&reset_external=true&release_offload_memory=true&malloc_trim=true&resume=true"
  }
}
```

Execute calls wrap the vLLM response as:

```json
{
  "format": "ds4-spark-trim-memory-result-v1",
  "ok": true,
  "execute": true,
  "response": {
    "ok": true,
    "status": 200,
    "json": {
      "status": "ok"
    }
  }
}
```

The low-level endpoint is still `POST /v1/trim_memory`; it is only for manual
debugging. Client code should use `tool:spark.trim_memory` or
`ds4_infer.cli trim-spark-memory`.

## Runtime Installation

The endpoint belongs in the `experiencenow-ai/vllm` fork, not in a Spark-side
startup patcher. Production DSV4 and Qwen runtimes must be built from a fork
revision that registers `vllm.entrypoints.serve.trim_memory_api`; otherwise the
contract path will 404 even though the DS4 control layer resolves it correctly.
