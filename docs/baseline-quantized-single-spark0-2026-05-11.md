# Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash IQ2XXS)

Date (UTC): 2026-05-11T05:34:47Z

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

- ds4_on_spark commit: `d4d8fec779f1a2831928bde4d758f398928f5010`
- Upstream commit(s):
  - llama.cpp fork (`/home/spark0/src/llama.cpp-kamnxt`): `fd89556567057bf64a6f6d6e50abec488929d7e0`

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

Local runner output dir (not committed): `/private/tmp/ds4_on_spark_baseline/20260511T053447Z`

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

- `ttft_first_output_s=0.055915`

Prefill throughput:

- `prefill_tps=22.7` (ctx=512, prompt=default)

Generation throughput:

- `generation_tps=16.0` (`output_tokens=8`)
- `decode_tps=16.0` (alias)

Wall time:

- `total_wall_s=NA` (not recorded in this committed report; re-run required to capture the baseline-summary block)

Flash Attention scheduling signal:

- `fattn_unique_nodes=43` (nonzero `__fattn__-*` schedule lines observed)

Patch probes (read-only; wrapper now runs these by default):

- `fattn_patch_probe=NA` (not recorded in this committed report; re-run required)
- `multislot_patch_probe=NA` (not recorded in this committed report; re-run required)

Memory:

- `max_rss_kb=84998376` (~81.1 GiB RSS, child process; best-effort)
- GPU mem: `nvidia-smi` reports memory usage as `Not Supported` on this host

Failure modes:

- Exit code: `0` (success)
