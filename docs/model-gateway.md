# DS4 Model Gateway

`scripts/ds4_vllm_lazy_proxy.py` is the OpenAI-compatible front door for Spark
model serving. It keeps the existing lazy vLLM behavior and also routes GGUF
models through non-vLLM backends.

## Backends

- `vllm_lazy_hf`: discovers HF-style model dirs under `MODELS_ROOT`
  (default `~/models/hf`) and starts `vllm serve` on first use.
- `vllm_remote`: forwards selected models to a remote OpenAI-compatible service,
  for example the Spark4 DeepSeek V4 endpoint.
- `ds4_server`: discovers GGUFs under `GGUF_MODELS_ROOT` (default
  `~/models/ds4`) and starts antirez `ds4-server` with the MTP sidecar when
  present.
- `llama_server`: available for explicit JSON specs that should start
  `llama-server` instead of `ds4-server`.

The gateway exposes:

- `/v1/models`
- `/v1/chat/completions`
- `/ds4/status`
- `/ds4/gpu`
- `/ds4/batches`
- `/ds4/release`

## Automatic Tuning

The caller should keep using ordinary OpenAI-compatible requests. Model-specific
runtime details are selected inside the gateway.

Default GB10/Spark vLLM policy:

- `--max-num-seqs 64`
- `--max-num-batched-tokens 32768`
- `--gpu-memory-utilization 0.75`
- `--enable-chunked-prefill`
- `--enable-prefix-caching`
- `--async-scheduling`

Qwen3-family models also get the Qwen3 reasoning parser automatically. Coder,
GLM, and Phi mini model IDs get their matching tool parsers when recognized.
DeepSeek V4 HF models use FP8 KV cache unless overridden.

Qwen DFlash drafters are auto-discovered under `DS4_DFLASH_ROOT`
(default `~/models/hf/z-lab`). If a matching local directory exists, for example
`Qwen3.5-9B-DFlash`, the gateway adds:

- `--speculative-config {"method":"dflash",...,"num_speculative_tokens":15}`
- `--attention-backend flash_attn`
- `--max-num-seqs 16`
- `--gpu-memory-utilization 0.85`

Stage the public DFlash assets on a Spark node with:

```sh
scripts/ds4_stage_dflash_assets_spark.sh
```

`z-lab/Qwen3.6-27B-DFlash` is gated by Hugging Face repository approval; the
script downloads it automatically when the Spark host has an approved HF login.

Per-model overrides can be supplied without changing callers:

```sh
DS4_GATEWAY_TUNING_JSON='{
  "models": {
    "Qwen/Qwen3.6-27B-FP8": {
      "max_num_seqs": 16,
      "gpu_memory_utilization": "0.85",
      "speculative_config": {
        "method": "dflash",
        "model": "/home/spark2/models/hf/z-lab/Qwen3.6-27B-DFlash",
        "num_speculative_tokens": 15
      }
    }
  }
}' $HOME/bin/ds4_vllm_lazy_proxy.sh
```

The same JSON may be put in a file and passed as `DS4_GATEWAY_TUNING_FILE`.
`/ds4/status` reports the effective `model_tuning` and active backend args so
benchmark results are tied to the actual runtime flags.

## Benchmark All Models

Use the all-model runner against a gateway from the Spark host itself:

```sh
scripts/ds4_gateway_benchmark_all.py \
  --base http://127.0.0.1:8000 \
  --concurrency 1,4 \
  --max-prompts 4 \
  --out-dir /tmp/ds4_gateway_bench/$(date -u +%Y%m%dT%H%M%SZ)
```

Outputs:

- `manifest.json`: model inventory, gateway status, and tuning metadata
- `runs.json`: per-model/per-concurrency benchmark records
- `summary.csv`: compact table for scoring and spreadsheet work
- `summary.md`: readable report with decode tok/s, aggregate tok/s, TTFT, errors

Optional public target comparisons can be added with `--targets-json`; unmatched
models are left unjudged rather than compared to non-equivalent Twitter numbers.

## Spark0 Antirez Smoke

Verified on Spark0 using:

```sh
FRONT_PORT=18090 BACKEND_PORT=18091 LOG_DIR=$HOME/vllm-lazy-logs-18090 \
  WAIT=1 $HOME/bin/ds4_vllm_lazy_proxy.sh

curl -sS --http1.1 -m 900 \
  -H 'content-type: application/json' \
  -d '{"model":"ds4-antirez","messages":[{"role":"user","content":"Reply with exactly OK."}],"max_tokens":4,"temperature":0,"thinking":{"type":"disabled"}}' \
  http://127.0.0.1:18090/v1/chat/completions
```

Result: HTTP 200, model `deepseek-v4-flash`, content `OK`.

## GPU Visibility

Use the Mac-side poller for a ring-wide snapshot:

```sh
scripts/ops_spark_gpu_status.sh
scripts/ops_spark_gpu_status.sh --watch --interval 5
```

It reports `gpu_used_pct` from `nvidia-smi utilization.gpu` for spark0 through
spark7 by default. On GB10 unified-memory hosts, `nvidia-smi` may report
`memory.total` and `memory.used` as `N/A`.

## Standard Batch API

The gateway exposes one higher-level synchronous batching API across all
backends:

```sh
curl -sS \
  -H 'content-type: application/json' \
  -d '{
    "model": "ds4-antirez",
    "concurrency": 4,
    "max_tokens": 32,
    "items": [
      {"custom_id":"a","prompt":"Return OK"},
      {"custom_id":"b","messages":[{"role":"user","content":"Return JSON with key ok"}]}
    ]
  }' \
  http://127.0.0.1:18090/ds4/batches
```

Response shape:

```json
{
  "object": "ds4.batch",
  "status": "completed",
  "counts": {"total": 2, "succeeded": 2, "failed": 0},
  "results": [
    {"index": 0, "custom_id": "a", "ok": true, "status": 200, "response": {}}
  ]
}
```

Rules:

- A batch must resolve to one model. This avoids local lazy backends killing
  each other while a mixed-model batch is still running.
- Results are returned in input order.
- `stream` is forced off inside batches.
- `BATCH_MAX_ITEMS`, `BATCH_MAX_CONCURRENCY`, and
  `BATCH_DEFAULT_CONCURRENCY` bound the gateway-level scheduler.

Runtime behavior still depends on the backend: vLLM batches concurrent requests
internally, `llama-server` can use multi-slot scheduling, and `ds4-server`
shares the same API but may serialize work internally.

Use the helper script to submit JSONL into `/ds4/batches` and receive JSONL
results:

```sh
printf '%s\n' \
  '{"prompt":"Return OK"}' \
  '{"messages":[{"role":"user","content":"Return JSON with key ok"}]}' |
scripts/ds4_gateway_batch_submit.py \
  --base http://127.0.0.1:18090 \
  --model ds4-antirez \
  --concurrency 4 \
  --max-tokens 32
```
