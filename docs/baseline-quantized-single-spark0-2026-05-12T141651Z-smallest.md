# Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash IQ2XXS auto-select smallest)

Date (UTC): 2026-05-12T14:16:51Z

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

```text
aitopatom-9ab9
Linux aitopatom-9ab9 6.17.0-1014-nvidia #14-Ubuntu SMP PREEMPT_DYNAMIC Tue Mar 17 19:01:40 UTC 2026 aarch64 aarch64 aarch64 GNU/Linux
Tue May 12 23:16:49 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.142                Driver Version: 580.142        CUDA Version: 13.0     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GB10                    On  |   0000000F:01:00.0 Off |                  N/A |
| N/A   56C    P0             13W /  N/A  | Not Supported          |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            4008      G   /usr/lib/xorg/Xorg                      101MiB |
|    0   N/A  N/A            4187      G   /usr/bin/gnome-shell                     48MiB |
|    0   N/A  N/A         1106325    C+G   ...c/gnome-remote-desktop-daemon        176MiB |
+-----------------------------------------------------------------------------------------+
```

## Repo + Upstream Revisions

- ds4_on_spark commit: `c59b5abe2721cb0d75af1d8cbf5babe4112da8cc`
- Upstream commit(s):
  - llama.cpp fork: `9222e55c13c965ccb7e9104fda58796edd84a732`
  - runtime_label: `v4flash-external`
  - llama_cli: `/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli`

## Fixture Manifest

```text
Fixture:
  type: gguf
  path: /home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf
  sha256: 31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c
  size_bytes: 86720111200
  runtime_label: v4flash-external
  notes: staged:/home/spark0/models/ds4 (auto-select smallest trunk) (IQ2XXS auto-select smallest)
```

## Command Line

Remote llama env (from baseline report):

```sh
ALLOW_RUN=1 MODEL_SOURCE='staged:/home/spark0/models/ds4 (auto-select smallest trunk)' MODEL_QUANT='IQ2XXS auto-select smallest' MODEL_GGUF='/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf' LLAMA_CLI='/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli' LLAMA_DIR='/home/spark0/src/llama.cpp-kamnxt' RUNTIME_LABEL='v4flash-external' CTX='512' N_TOKENS='8' N_GPU_LAYERS='99'
```

## Results

Quality:

- public_quality_prior: NA
- public_quality_basis/source: NA
- local_quality_score: NA
- passed_tasks: NA
- total_tasks: NA
- quality_score: NA

Quality/Speed scoring (from `scripts/model_quality_speed_score.py`, when available):

- quality_adjusted_decode_tps: `NA`
- correct_task_rate: `NA`
- tokens_per_success: `NA`
- dominated_by: `NA`

GGUF contract inspector (metadata-only):

- weight_keys_sha256=0d7226bd7c13c2cfa43a16a04b4b9a69b9b0940df4c859030e1de0e74c5c5ddc
- tensor_key_namespace_guess=llama.cpp
- trunk_contract: kind=llama.cpp complete=True
- mtp_contract: checked=False reason=no mtp.* tensors present
- quantization_contract: checked=True dense=F32 expert=IQ2_XXS dense_fp8_like=False expert_fp4_like=False
- mtp_present=false

Core metrics (from `== baseline summary (approx) ==`):

- ttft_s: `0.056846`
- prefill_tps: `22.900000`
- decode_tps: `14.800000`
- total_wall_s: `516.176880`
- output_tokens: `8`
- max_rss_kb: `85003332`

Timing breakdown (from `llama_print_timings`, when available):

- NA (timings not captured by the runtime)

Flash Attention scheduling signal (from baseline summary):

- fattn_unique_nodes: `43`
- fattn_log_lines: `4730`

Patch probes (read-only):

- fattn_patch_probe.pad256_found=true
- multislot_patch_probe.reserve_cap_n_ctx_seq_found=true
- multislot_patch_probe.swa_stream_view_found=false
- multislot_patch_probe.reserve_bound_tokens_found=true
- multislot_patch_probe.skip_impossible_windows_found=true

Raw summary block:

```text
exit_code=0
llama_cli=/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli
llama_commit=9222e55c13c965ccb7e9104fda58796edd84a732
runtime_label=v4flash-external
model_source=staged:/home/spark0/models/ds4 (auto-select smallest trunk)
model_quant=IQ2XXS auto-select smallest
model_gguf=/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf
model_sha256=31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c
ctx=512
n_tokens=8
n_gpu_layers=99
model_size_bytes=86720111200
ttft_first_output_s=0.056846
ttft_s=0.056846
wall_s=516.176880
total_wall_s=516.176880
max_rss_kb=85003332
prefill_tps=22.900000
generation_tps=14.800000
decode_tps=14.800000
output_tokens=8
fattn_log_lines=4730
fattn_unique_nodes=43
fattn_cli_probe_path=/tmp/baseline_llamacpp/fattn_cli_probe.json
```
