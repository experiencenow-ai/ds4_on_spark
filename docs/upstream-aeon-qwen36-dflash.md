# Upstream: AEON-7 Qwen3.6 27B DFlash On DGX Spark

This note extracts Spark-relevant operating lessons from AEON-7's public
Qwen3.6 27B DFlash work. It is metadata/runbook only: no model weights were
downloaded while preparing this document.

## Sources And Attribution

- GitHub: `AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-DFlash`
  - URL: `https://github.com/AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-DFlash`
  - Inspected commit: `67be1e0e8450a8f1ba68793563a1266ab7197363`
  - License: Apache-2.0
- GitHub: `AEON-7/vllm-dflash`
  - URL: `https://github.com/AEON-7/vllm-dflash`
  - Inspected commit: `4efa0929a01f06a96fe7a10bd74652b1e2380f19`
  - License: Apache-2.0
- Model body: `AEON-7/Qwen3.6-27B-AEON-Ultimate-Uncensored-Multimodal-NVFP4-MTP-XS`
  - HF commit: `6394b93fa092dcbfbf09e952f56f30337509d17c`
  - License: Apache-2.0
  - Safetensors: 20,559,273,880 bytes (19.15 GiB)
- DFlash drafter: `z-lab/Qwen3.6-27B-DFlash`
  - HF commit: `0919688658996800f86b895034249700e9481106`
  - License: MIT
  - Safetensors: 3,460,432,504 bytes (3.22 GiB)

Attribution: all AEON-specific performance claims and DGX Spark recipe details
below are credited to AEON-7. Local ds4_on_spark results must be measured on our
own Spark(s) before we treat them as decision-grade.

## Most Useful Takeaways

1. The strongest public 27B-class Spark recipe found so far is AEON's
   `qwen36-v4` container with the XS modelopt body plus external DFlash.
2. On DGX Spark, AEON explicitly uses external DFlash (`method=dflash`, `k=15`)
   rather than the model's grafted native MTP head. Native Qwen MTP is positioned
   for dedicated-VRAM Blackwell, not Spark unified memory.
3. The measured v4 stack is not stock vLLM. It uses a patched AEON container,
   FlashInfer 0.6.11, CUTLASS NVFP4 for SM121, CUDA graphs, Qwen3 reasoning
   parsing, and a DFlash sliding-window-attention compatibility patch.
4. Spark unified memory is the operational constraint. AEON's profiles use
   `gpu-memory-utilization=0.75` for gateway/mixed workloads and `0.85` for
   solo long-context LLM service, with a hard warning not to exceed about `0.88`.
5. Benchmarking must be streaming. Measure TTFT from the first streamed content
   or reasoning delta, and measure decode throughput from streamed usage
   `completion_tokens`, not from wall clock around a blocking API call.
6. DFlash speed is prompt-class sensitive. Structured/code/JSON prompts get the
   best acceptance; free-form prose is closer to base decode. This matters for
   our "short answer / judge" plan because classifier, JSON, and multiple-choice
   outputs should be high-acceptance shapes.

## AEON Public Performance Signal

AEON's v4 README reports this DGX Spark comparison:

| Deployment | Container | DFlash | Avg c=1 decode |
| --- | --- | ---: | ---: |
| Raw baseline | `vllm/vllm-openai:nightly` | off | 10.49 tok/s |
| AEON v4 DFlash | `ghcr.io/aeon-7/vllm-aeon-ultimate-dflash:qwen36-v4` | k=15 | 37.56 tok/s |

Their single-stream v4 prompt-class table reports:

| Category | v4 decode | TTFT | TPOT |
| --- | ---: | ---: | ---: |
| Coding | 31.89 tok/s | 191 ms | 30.5 ms |
| Math | 37.76 tok/s | 225 ms | 25.5 ms |
| Reasoning | 42.41 tok/s | 221 ms | 22.6 ms |
| Prose | 31.85 tok/s | 212 ms | 30.4 ms |
| Natural language | 31.99 tok/s | 183 ms | 30.3 ms |
| Extraction / JSON | 49.48 tok/s | 227 ms | 19.2 ms |

For c=16 aggregate serving, AEON reports the biggest v4 gains on structured
math/reasoning/extraction workloads. Treat the c=256 table in upstream docs as a
saturation stress test, not an interactive target.

The older `AEON-7/vllm-dflash` Qwen3.5 27B repo reports even higher class-specific
numbers for code (64 tok/s c=1, 327 tok/s aggregate c=16), but that is a different
target/model stack. It is still useful evidence that DFlash acceptance is the key
variable and that c=16 can be a real serving point when memory is tuned correctly.

## Spark Runtime Recipe To Test Locally

Use the compose example added in this repo:

```sh
docker compose -f deploy/compose/aeon-qwen36-dflash.spark-xs.yml.example up -d
```

Expected local model paths are configurable via environment variables:

```sh
export AEON_TARGET_MODEL_PATH=/var/lib/ds4/models/aeon-qwen36-mmtp-xs
export AEON_DFLASH_DRAFTER_PATH=/var/lib/ds4/models/qwen36-dflash
```

Core runtime choices to preserve for the first local run:

- image: `ghcr.io/aeon-7/vllm-aeon-ultimate-dflash:qwen36-v4`
- target body: modelopt XS variant, served with `--quantization modelopt`
- drafter: `z-lab/Qwen3.6-27B-DFlash`
- speculative config: `{"method":"dflash","model":"/models/dflash-drafter","num_speculative_tokens":15}`
- `TORCH_CUDA_ARCH_LIST=12.1a`
- `ENABLE_NVFP4_SM100=0`
- `VLLM_NVFP4_GEMM_BACKEND=flashinfer-cutlass`
- `--enable-chunked-prefill`
- `--enable-prefix-caching`
- `--reasoning-parser qwen3`
- `--tool-call-parser qwen3_coder`

Start with the gateway profile, then only move to solo-LLM settings after a
healthy baseline:

| Profile | max model len | max seqs | max batched tokens | GPU memory util |
| --- | ---: | ---: | ---: | ---: |
| gateway/mixed | 256000 | 64 | 32768 | 0.75 |
| solo long-context LLM | 200000 | 16 | 32768 | 0.85 |
| benchmark short-context | 2048 | up to 256 | 32768 | local test |

## Benchmarking Added Here

Use the generic streaming benchmark added in this PR:

```sh
scripts/benchmark_openai_chat_stream.py \
  --endpoint http://localhost:8000/v1/chat/completions \
  --model aeon-ultimate \
  --thinking off \
  --concurrency 1 \
  --jsonl-out /tmp/aeon-qwen36-c1.jsonl \
  --csv-out /tmp/aeon-qwen36-c1.csv
```

Then test aggregate/batched behavior:

```sh
scripts/benchmark_openai_chat_stream.py \
  --endpoint http://localhost:8000/v1/chat/completions \
  --model aeon-ultimate \
  --thinking off \
  --concurrency 16 \
  --jsonl-out /tmp/aeon-qwen36-c16.jsonl \
  --csv-out /tmp/aeon-qwen36-c16.csv
```

Quality/speed scoring can consume the CSV after adding local quality fields, or
it can use the raw `decode_tps`, `ttft_s`, `total_wall_s`, and `output_tokens`
columns as the speed side of the tradeoff.

## Diagnostics To Add To Spark Runs

After a benchmark, capture:

```sh
curl -s http://localhost:8000/metrics | grep -E 'spec_decode|draft_acceptance|dflash' || true
docker ps --filter 'name=aeon-qwen36-dflash' --format '{{.Image}} {{.Status}}'
docker logs aeon-qwen36-dflash --tail 200
```

Expected shape if DFlash is actually active:

- nonzero speculative decode / draft acceptance metrics after requests
- container image pinned to `qwen36-v4`
- no fallback to Marlin or stock vLLM
- no CPU fallback or unified-memory thrash

## Implications For Our Plan

- Add AEON Qwen3.6 XS+DFlash as the top 27B Qwen comparator before spending more
  time on unoptimized Qwen 27B target-only runs.
- Keep DeepSeek V4 Flash MTP work separate. AEON proves the Spark can do strong
  27B-class DFlash throughput, but it does not solve DeepSeek's expert routing or
  native MTP contract.
- Use short, structured judge outputs for DSV4 and Qwen because DFlash and MTP
  both reward low-entropy continuations.
- For multi-model ELO, AEON Qwen can be one "fast judge/candidate" arm, while
  DSV4 remains the slow high-value judge arm until its MTP path improves.
- Do not import AEON's uncensored model as a production default without a safety
  decision. It is useful as a performance comparator and local research target;
  quality/safety posture should be scored separately from tok/s.
