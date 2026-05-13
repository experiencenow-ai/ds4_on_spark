# Baseline: Quantized Single-Spark Spark0 (DeepSeek V4 Flash auto: smallest_by_size_bytes (exclude: MTP|DFlash|draft|sidecar; include: IQ2|Q2_K|IQ3|Q3_K))

Date (UTC): 2026-05-13T08:01:11Z

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
Wed May 13 17:01:09 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.142                Driver Version: 580.142        CUDA Version: 13.0     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GB10                    On  |   0000000F:01:00.0 Off |                  N/A |
| N/A   57C    P0             13W /  N/A  | Not Supported          |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            4008      G   /usr/lib/xorg/Xorg                      101MiB |
|    0   N/A  N/A            4187      G   /usr/bin/gnome-shell                     48MiB |
|    0   N/A  N/A         1719489    C+G   ...c/gnome-remote-desktop-daemon        176MiB |
+-----------------------------------------------------------------------------------------+
```

## Repo + Upstream Revisions

- ds4_on_spark commit: `b9eaa1ff23959b4f0a19532bb8dca3843b3a4616`
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
  notes: staged:/home/spark0/models/ds4 (auto-select smallest trunk) (auto: smallest_by_size_bytes (exclude: MTP|DFlash|draft|sidecar; include: IQ2|Q2_K|IQ3|Q3_K))
```

## Command Line

Remote llama env (from baseline report):

```sh
ALLOW_RUN='1' MODEL_SOURCE='staged:/home/spark0/models/ds4 (auto-select smallest trunk)' MODEL_QUANT='auto: smallest_by_size_bytes (exclude: MTP|DFlash|draft|sidecar; include: IQ2|Q2_K|IQ3|Q3_K)' MODEL_GGUF='/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf' MODEL_GGUF_GLOB='/home/spark0/models/ds4/*.gguf' MODEL_GGUF_EXCLUDE_EGREP='MTP|DFlash|draft|sidecar' MODEL_GGUF_INCLUDE_EGREP='IQ2|Q2_K|IQ3|Q3_K' MODEL_GGUF_SELECT='smallest_by_size_bytes' LLAMA_CLI='/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli' LLAMA_DIR='/home/spark0/src/llama.cpp-kamnxt' RUNTIME_LABEL='v4flash-external' CTX='512' N_TOKENS='32' N_GPU_LAYERS='99'
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
- topology_contract: checked=True mismatch_count=0
- trunk_contract: kind=llama.cpp complete=True
- mtp_contract: checked=False reason=no mtp.* tensors present
- mtp_namespace: has_mtp0=False expected_complete=False present_prefixes=[]
- mtp_preservation: status=absent preserves=False mtp_keys_sha256_match_official=None
- mtp_trust: status=absent trusted=False mtp_keys_sha256_match_official=None
- mtp_trust_reason_first=no mtp.* tensors present
- quantization_contract: checked=True dense=F32 expert=IQ2_XXS dense_fp8_like=False expert_fp4_like=False
- execution_contract_sha256=c380b82b59751d01abf047d58084f364a6abcf37393df9710ecb75877a8ee24d
- upstream_x_repo_commit=6976c7ff1b30a1b2cb7805021b8ba4684041f136
- mtp_present=false

Core metrics (from `== baseline summary (approx) ==`):

- ttft_s: `0.068333`
- prefill_tps: `22.700000`
- decode_tps: `13.700000`
- total_wall_s: `525.602011`
- output_tokens: `32`
- max_rss_kb: `85003488`

Timing breakdown (from `llama_print_timings`, when available):

- NA (timings not captured by the runtime)

Flash Attention scheduling signal (from baseline summary):

- fattn_unique_nodes: `43`
- fattn_log_lines: `9890`

Patch probes (read-only):

- fattn_patch_probe.llama_rev: `9222e55c13c965ccb7e9104fda58796edd84a732`
- fattn_patch_probe.pad256_found=true
- fattn_patch_probe.pad256_confidence: `high`
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
model_quant=auto: smallest_by_size_bytes (exclude: MTP|DFlash|draft|sidecar; include: IQ2|Q2_K|IQ3|Q3_K)
model_gguf=/home/spark0/models/ds4/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2.gguf
model_sha256=31598c67c8b8744d3bcebcd19aa62253c6dc43cef3b8adf9f593656c9e86fd8c
ctx=512
n_tokens=32
n_gpu_layers=99
model_size_bytes=86720111200
ttft_first_output_s=0.068333
ttft_s=0.068333
wall_s=525.602011
total_wall_s=525.602011
max_rss_kb=85003488
prefill_tps=22.700000
generation_tps=13.700000
decode_tps=13.700000
output_tokens=32
fattn_log_lines=9890
fattn_unique_nodes=43
fattn_cli_probe_path=/tmp/baseline_llamacpp/fattn_cli_probe.json
```
