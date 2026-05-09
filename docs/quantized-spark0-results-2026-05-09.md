# Quantized Spark0 Results - 2026-05-09

This records the first single-Spark quantized DeepSeek V4 Flash experiments on
Spark0. Claims here are tied to the local report paths and remote command lines
emitted by `scripts/run_baseline_existing_runtime.sh`.

## Hardware And Artifact

- Host: `spark0@aitopatom-9ab9.local`
- GPU: NVIDIA GB10, CUDA 13.0 driver stack, compute capability 12.1
- RAM: about 119 GiB
- Main model:
  `/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf`
- Main model size: `86720111200` bytes
- Main model sha256:
  `31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c`
- MTP model:
  `/home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf`
- MTP model size: `3807602400` bytes

## Runtime Matrix

| Runtime | Result | Notes |
| --- | --- | --- |
| `antirez/llama.cpp-deepseek-v4-flash@2f2d440` | Fails | Main model loads, then CUDA path asserted in concat or DS4 compressed-cache setup. |
| `nisparks/llama.cpp@9d36408` | Fails fast | Requires `hc_head_base`, which is not present in the downloaded main GGUF contract. |
| `kamnxt/llama.cpp-deepseek-v4-flash-cuda-spark@9222e55` | Passes | First successful main-model run on Spark0. |

## Successful Main-Model Smoke

Report:
`/private/tmp/ds4_kamnxt_v4_smoke1/20260509T110949Z/baseline_existing_runtime.md`

Command shape:

```sh
/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli \
  -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  -p Hello. -n 1 -c 512 -ngl 99 --perf \
  --cache-ram -1 --fit off --single-turn --no-display-prompt --simple-io --no-warmup
```

Summary:

- Exit code: `0`
- Wall time: `472.860603` seconds
- Max RSS: `87038906368` bytes
- Prompt eval: `20.2` tok/s
- Main GGUF reports no embedded MTP tensors: `gguf_has_mtp=False`,
  `gguf_mtp_tensor_count=0`

The one-token generation rate is not meaningful; this was only a load and
first-token smoke.

## Resident Server Probe

Server command shape:

```sh
/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-server \
  -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  -c 512 -ngl 99 --host 127.0.0.1 --port 18080 --perf \
  --cache-ram -1 --fit off --no-warmup --no-webui --cache-prompt \
  --parallel 1 --log-verbosity 2
```

Startup:

- Started in `/tmp/ds4_kamnxt_server_20260509T111850Z`
- `/health` returned `{"status":"ok"}` after about `14:08` elapsed
- During load, `/health` correctly returned `503 Loading model`

Loaded-server request measurements:

| Endpoint | Tokens | Wall | Prompt tok/s | Generation tok/s |
| --- | ---: | ---: | ---: | ---: |
| `/v1/chat/completions` | 32 | `3.016250`s | `23.56` | `12.83` |
| `/v1/chat/completions` repeat | 32 | `2.652837`s | `47.99` | `13.30` |
| `/completion` | 32 | `2.687192`s | `35.56` | `12.91` |
| `/completion` repeat | 32 | `2.617231`s | `36.66` | `13.30` |
| `/completion` | 128 | `10.900452`s | `50.83` | `12.33` |

This confirms that the long load must be amortized by a resident server. Once
loaded, the single-Spark quantized path is interactive enough for short requests,
with generation around 12-13 tok/s at `ctx=512`.

## Input Size Sweep

A second resident server was started with `ctx=8192` to separate tiny-prompt
overhead from longer prefill behavior:

```sh
/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-server \
  -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  -c 8192 -ngl 99 --host 127.0.0.1 --port 18080 --perf --metrics \
  --cache-ram -1 --fit off --no-warmup --no-webui --cache-prompt \
  --parallel 1 --log-verbosity 2
```

Startup:

- Started in `/tmp/ds4_kamnxt_server_sweep_20260509T120000Z`
- `/health` returned `{"status":"ok"}` after about `09:10` elapsed

Fresh prefill sweep (`cache_prompt=false`, `n_predict=8`):

| Target words | Actual prompt tokens | Wall | Prompt tok/s | Generation tok/s |
| ---: | ---: | ---: | ---: | ---: |
| 64 | 77 | `1.640449`s | `79.67` | `13.72` |
| 256 | 269 | `1.535831`s | `305.60` | `12.69` |
| 1024 | 1038 | `4.341187`s | `283.22` | `12.34` |
| 2048 | 2062 | `8.489412`s | `266.41` | `11.58` |
| 4096 | 4110 | `17.218234`s | `250.15` | `11.21` |
| 6144 | 6158 | `26.026841`s | `244.53` | `10.77` |

Same-prompt cache reuse at the 4096-word size (`cache_prompt=true`,
`n_predict=8`):

| Run | Prompt tokens evaluated | Cache tokens reused | Wall | Prompt tok/s | Generation tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4108 | 0 | `17.066034`s | `253.71` | `11.33` |
| 2 | 516 | 3592 | `3.165983`s | `209.68` | `11.53` |

The earlier 50 tok/s result was therefore a tiny-prompt loaded-server artifact,
not the longer-prompt prefill ceiling. At thousands of prompt tokens, this
runtime is around 245-305 prompt tok/s on Spark0 with the current CUDA fallback
mix. Prompt-cache reuse is active and materially reduces repeated prompt work.

## Flash-Attention Reservation Finding

The slow sweep above exposed a graph scheduling issue in the Spark CUDA fork.
The server log showed `__fattn__-2` through `__fattn__-42` rejected with shape
`Q[512,1,64,1] K[512,1,1,1] V[512,1,1,1]`, followed by:

```text
sched_reserve: layer 2 is assigned to device CUDA0 but the Flash Attention tensor is assigned to device CPU (usually due to missing support)
sched_reserve: Flash Attention was auto, set to disabled
```

The rejection came from `ggml_cuda_get_best_fattn_kernel`: head dimension 512
requires the GQA-optimized path, which requires `K->ne[1] % 256 == 0`. The
reservation graph hit a DS4 prefill/no-compressed-token path with `K->ne[1] == 1`
and disabled Flash Attention globally before the long-prompt requests.

Experimental Spark0 patch:

- Runtime tree: `/home/spark0/src/llama.cpp-kamnxt`
- Patch note: `docs/patches/llama-cpp-kamnxt-ds4-fattn-reservation.patch`
- Patched file: `src/models/deepseek4.cpp`
- Change: in the DS4 `is_prefill && n_comp == 0` raw-window path, when Flash
  Attention is enabled and `n_embd_head_k == 512`, pad `kv` and the mask to the
  next 256-token boundary.
- Cleanup: removed the temporary `[cuda] ACCEPT/REJECT __fattn__` debug prints
  from `ggml/src/ggml-cuda/ggml-cuda.cu` for clean measurement.
- Note: this fork still emits verbose scheduler placement traces for `__fattn__`
  nodes, so the patched probe may still include some logging overhead.

After rebuilding `llama-server`, the same reservation flow assigned all
`__fattn__-0..42` nodes to CUDA backend `0`; the global Flash Attention disable
line was gone.

Clean patched probe (`ctx=8192`, `cache_prompt=false`, `n_predict=8`, port
`18081`):

| Target words | Actual prompt tokens | Wall | Prompt tok/s | Generation tok/s |
| ---: | ---: | ---: | ---: | ---: |
| 256 | 257 | `1.588358`s | `253.27` | `15.21` |
| 1024 | 1025 | `3.536987`s | `340.82` | `15.28` |
| 4096 | 4097 | `14.645170`s | `293.12` | `12.47` |

Conclusion: the `__fattn__` issue was real and worth fixing, but it is not the
whole 10x gap. It restores CUDA Flash Attention scheduling and modestly improves
the 4k prompt probe from about 250 tok/s to about 293 tok/s, while generation
remains around 12-15 tok/s. The next bottleneck is elsewhere in the DS4 graph,
likely expert routing/dispatch, quantized matmuls, compressed-cache/indexer work,
or remaining scheduler overhead.

## Resident 16k Context Sweep

`scripts/benchmark_llamacpp_server_sweep.py` was added to make loaded-server
measurements repeatable. It starts `llama-server`, waits for `/health`, runs
deterministic `/completion` prompts, and writes JSONL plus a markdown summary.

Command shape:

```sh
OUT_DIR=/tmp/ds4_server_sweep_ctx16384_run1 \
LLAMA_SERVER=/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-server \
MODEL_GGUF=/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
CTX=16384 PORT=18082 PROMPT_WORDS="64 256 1024 4096 8192 12288" \
N_PREDICT=8 CACHE_PROMPT=0 KEEP_SERVER=1 WAIT_TIMEOUT_S=1200 \
SERVER_ARGS="--cache-ram -1 --fit off --no-warmup --no-webui --cache-prompt --parallel 1 --log-verbosity 0 --metrics" \
/tmp/benchmark_llamacpp_server_sweep.py
```

Startup:

- `ctx=16384` resident server reached `/health` in `465.989812` seconds.
- Server stayed resident on port `18082` for follow-up warm probes.
- The server log for this run had `__fattn__` nodes assigned to CUDA backend
  `0` and no `Flash Attention was auto, set to disabled` line.

Fresh prefill sweep (`cache_prompt=false`, `n_predict=8`):

| Prompt tokens | Wall | Prompt tok/s | Generation tok/s | Notes |
| ---: | ---: | ---: | ---: | --- |
| 160 | `1.744356`s | `164.51` | `15.43` | Tiny prompts are overhead dominated. |
| 640 | `3.803451`s | `210.51` | `14.09` |  |
| 2560 | `11.791263`s | `239.52` | `14.34` |  |
| 10240 | `48.700507`s | `213.02` | `13.58` |  |
| 12800 | `61.908841`s | `208.83` | `13.46` | Warm follow-up run. |
| 15360 | `76.141812`s | `203.45` | `13.32` | Near 16k context limit. |
| 16000 | `79.321369`s | `203.37` | `13.33` | Near 16k context limit. |

The deterministic prompt tokenizes at about 2.5 tokens per target word. The
8192-word and 12288-word requests correctly failed against `ctx=16384` with
`exceed_context_size_error` at 20480 and 30720 prompt tokens.

Prompt-cache reuse on the already-loaded server (`cache_prompt=true`, same
10240-token prompt repeated):

| Run | Prompt tokens evaluated by timings | Cache field | Wall | Prompt tok/s | Generation tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 2048 | 10247 | `11.181921`s | `193.80` | `13.70` |
| 1 | 516 | 10247 | `3.462051`s | `182.82` | `12.87` |

This confirms useful prefix reuse inside the resident server. The exact timing
fields are server-specific: for cached requests, `timings.prompt_n` is the
amount newly evaluated for that request, while `tokens_evaluated` in the raw
JSON still reports the full prompt token count.

## Resident 32k Context Sweep

The 16k resident server was stopped and a `ctx=32768` server was started with
the same runtime and model on port `18083`.

Startup:

- `ctx=32768` resident server reached `/health` in `460.441871` seconds.
- The process remained healthy after the sweep and was left resident for
  follow-up probes.

Fresh prefill sweep (`cache_prompt=false`, `n_predict=8`):

| Prompt tokens | Wall | Prompt tok/s | Generation tok/s |
| ---: | ---: | ---: | ---: |
| 20480 | `107.707830`s | `192.49` | `13.07` |
| 30720 | `171.762660`s | `179.55` | `12.97` |
| 32000 | `178.008088`s | `180.49` | `12.20` |

The long-context slope is now clearly below the 8k/16k prompt rate. At this
speed, ingesting 1M fresh prompt tokens would take roughly 90 minutes before
generation. That is not a viable target without deeper runtime work, aggressive
prefix reuse, or both.

## MTP Probe

Report:
`/private/tmp/ds4_kamnxt_v4_mtp_cli1/20260509T113651Z/baseline_existing_runtime.md`

Command shape:

```sh
/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli \
  -m /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf \
  -p Hello. -n 32 -c 512 -ngl 99 --perf \
  --cache-ram -1 --fit off --single-turn --no-display-prompt --simple-io --no-warmup \
  -md /home/spark0/models/ds4/DeepSeek-V4-Flash-MTP-Q4K-Q8_0-F32.gguf \
  -ngld 99 --draft 4 --draft-min 1 --draft-p-min 0.5
```

Summary:

- Exit code: `1`
- Wall time: `557.009502` seconds
- Max RSS: `87038730240` bytes
- Failure: `unknown model architecture: 'deepseek4_mtp_support'`

The MTP sidecar is valid and small enough to stage, but the CUDA Spark fork does
not yet register or execute the DS4-specific MTP architecture. The native
`antirez/ds4` code has the expected MTP tensor bindings and `--mtp` flow, but
that implementation is currently Metal-first.

## Next Work

1. Turn the Flash-Attention reservation fix into a narrow patch/probe artifact
   and add a regression check that `__fattn__` nodes stay on CUDA for DS4
   reservation and long-prompt graphs.
2. Profile the remaining DS4 CUDA graph bottlenecks now that Flash Attention
   schedules on GPU: expert routing/dispatch, quantized matmuls, compressed
   cache/indexer work, and scheduler overhead.
3. Port or implement `deepseek4_mtp_support` loading for the CUDA Spark path,
   using `antirez/ds4` as the tensor-contract reference.
4. Add larger context probes only after deciding whether the memory and time
   budget justify `ctx=65536` and above as separate long-load runs.
