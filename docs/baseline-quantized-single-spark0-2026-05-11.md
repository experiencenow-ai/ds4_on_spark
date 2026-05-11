# Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash IQ2XXS)

Date (UTC): 2026-05-11T20:25:25Z

Baseline type:

- [ ] antirez/ds4 (Mac / Metal)
- [x] llama.cpp (Spark / CUDA)
- [ ] vLLM (Spark / reference)
- [ ] Ling 2.6 Flash target-only (Spark / vLLM or SGLang)
- [ ] Qwen target-only (Spark / vLLM or SGLang)
- [ ] Qwen + DFlash draft (Spark / speculative)
- [ ] other target + DFlash draft (Spark / speculative)
- [ ] ds4_on_spark (future)

## Host

- Hostname: `aitopatom-9ab9` (Spark0)
- OS / kernel: `Linux 6.17.0-1014-nvidia` (aarch64)
- CPU: 20 cores (10x Cortex-X925 + 10x Cortex-A725)
- RAM: 119 GiB
- GPU: NVIDIA GB10 (compute capability 12.1)
- Driver / CUDA: NVIDIA-SMI 580.142 / CUDA 13.0

## Repo + Upstream Revisions

- ds4_on_spark commit: `6642ffb55a0ed6722ff56ac8fa65db6e07f64b69`
- Upstream commit(s):
  - llama.cpp fork (`/home/spark0/src/llama.cpp-kamnxt`): `9222e55c13c965ccb7e9104fda58796edd84a732`

Notes:

- The companion baseline wrapper now forwards `LLAMA_DIR` into the Spark-side llama.cpp runner; prior runs could print a revision for `$HOME/src/llama.cpp` even when `LLAMA_CLI` pointed at a different tree.

## Fixture Manifest

```text
Fixture:
  type: gguf
  path: /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf
  sha256: 31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c
  size_bytes: 86720111200
  notes: antirez/deepseek-v4-gguf@9cb905d (IQ2XXS chat-v2 gguf); MTP absent
```

## Command Line

Mac → Spark:

```sh
MODEL_SOURCE='antirez/deepseek-v4-gguf@9cb905d (IQ2XXS chat-v2 gguf)' \
MODEL_QUANT='IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2' \
MODEL_GGUF='/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf' \
LLAMA_CLI='/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli' \
CTX=512 N_TOKENS=8 N_GPU_LAYERS=99 \
scripts/run_quantized_single_spark.sh spark0@aitopatom-9ab9.local
```

Local runner output dir (not committed): `/private/tmp/ds4_on_spark_baseline/20260511T202525Z`

## Results

Quality:

- Public quality prior: NA
- Public quality basis/source: NA
- Local quality score: NA
- Passed tasks: NA
- Total tasks: NA
- Quality score: NA

GGUF contract inspector (metadata-only):

- `general.architecture=deepseek4`, `general.file_type=19`, `deepseek4.block_count=43`
- `mtp_present=false` (no `mtp.*` tensors detected)

TTFT:

- `ttft_first_output_s=0.051150`

Prefill throughput:

- `prefill_tps=19.1` (ctx=512, prompt=default)

Generation throughput:

- `generation_tps=14.6` (`output_tokens=8`)
- `decode_tps=14.6` (alias)

Wall time:

- `total_wall_s=397.882706`

Flash Attention scheduling signal:

- `fattn_unique_nodes=43` (nonzero `__fattn__-*` schedule lines observed)
- `fattn_log_lines=4730`

Patch probes (read-only; wrapper now runs these by default):

- `fattn_patch_probe.pad256_found=true` (head_dim=512 prefill pad-to-256 fix present)
- `multislot_patch_probe.reserve_cap_n_ctx_seq_found=true` (reserve bounded by per-sequence ctx)
- `multislot_patch_probe.swa_stream_view_found=false` (SWA current-stream view fix not detected)

Memory:

- `max_rss_kb=85003232` (~81.1 GiB RSS, child process; best-effort)
- GPU mem: `nvidia-smi` reports memory usage as `Not Supported` on this host

Failure modes:

- Exit code: `0` (success)
