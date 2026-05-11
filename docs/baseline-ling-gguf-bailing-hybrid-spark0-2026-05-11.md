# Baseline: Ling GGUF `bailing_hybrid` on Spark0 (llama.cpp; failed to load)

Date (UTC): 2026-05-11T11:58:21Z

Baseline type:

- [ ] antirez/ds4 (Mac / Metal)
- [x] llama.cpp (Spark / CUDA)
- [ ] vLLM (Spark / reference)
- [ ] Ling 2.6 Flash target-only (Spark / vLLM or SGLang)
- [ ] Qwen target-only (Spark / vLLM or SGLang)
- [ ] Qwen + DFlash draft (Spark / speculative)
- [ ] other target + DFlash draft (Spark / speculative)
- [ ] ds4_on_spark (future)

Purpose: attempt a cheap Ling-style target-only baseline using an already-staged Ling GGUF on Spark0. This run failed during model load because the runtime does not recognize the GGUF `general.architecture=bailing_hybrid`.

## Host

- Hostname: `aitopatom-9ab9` (Spark0)
- OS / kernel: `Linux 6.17.0-1014-nvidia` (aarch64)
- CPU: 20 cores (10x Cortex-X925 + 10x Cortex-A725)
- RAM: 119 GiB
- GPU: NVIDIA GB10 (compute capability 12.1)
- Driver / CUDA: NVIDIA-SMI 580.142 / CUDA 13.0

## Repo + Upstream Revisions

- ds4_on_spark commit: `db20e6f72a117b24c312557d5f5c8f2f742d7403`
- Upstream commit(s):
  - llama.cpp fork (`/home/spark0/src/llama.cpp-kamnxt`): `fd89556567057bf64a6f6d6e50abec488929d7e0`

## Fixture Manifest

```text
Fixture:
  type: gguf
  path: /home/spark0/models/ling/Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf
  sha256: a7d93e9cd3140b08f9188d3fd7db5c16f7f37b3c4bafa80cac1b2a8d95162831
  size_bytes: 61163862912
  notes: staged on Spark0 under /home/spark0/models/ling; gguf header reports general.architecture=bailing_hybrid; mtp absent
```

## Command Line

Mac → Spark:

```sh
MODEL_RUNS_CSV=/private/tmp/ds4_model_runs.csv \
RUN_LABEL=ling-iq4nl-unsupported-arch \
LLAMA_SCOPE=ling_target \
REMOTE_LLAMA_ENV='ALLOW_MODEL_INSPECT=1 ALLOW_RUN=1 RUNTIME_LABEL=llama.cpp-kamnxt MODEL_SOURCE="/home/spark0/models/ling/Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf" MODEL_QUANT=IQ4_NL MODEL_GGUF=/home/spark0/models/ling/Ling-2.6-flash-IQ4_NL-bailing_hybrid-20260505-LJ.gguf LLAMA_CLI=/home/spark0/src/llama.cpp-kamnxt/build-cuda/bin/llama-cli CTX=512 N_TOKENS=1 N_GPU_LAYERS=99' \
scripts/run_baseline_existing_runtime.sh spark0@aitopatom-9ab9.local
```

Local runner output dir (not committed): `/private/tmp/ds4_on_spark_baseline/20260511T115819Z-ling-iq4nl-unsupported-arch`

## Results

Quality:

- Public quality prior: NA
- Public quality basis/source: NA
- Local quality score: NA
- Passed tasks: NA
- Total tasks: NA
- Quality score: NA

GGUF contract inspector (metadata-only):

- `general.architecture=bailing_hybrid`, `general.file_type=25`, `bailing_hybrid.block_count=33`
- `mtp_present=false` (no `mtp.*` tensors detected)

Run outcome:

- Exit code: `1` (failed)
- Failure mode: llama.cpp model load failure (`unknown model architecture: 'bailing_hybrid'`)
- TTFT / speed: NA (no successful token generation)

Next step:

- Do not treat this GGUF as a valid Ling baseline until the selected external runtime can load `bailing_hybrid` artifacts; instead, prefer the planned Ling 2.6 Flash INT4 target-only baseline via vLLM/SGLang when the artifact is already staged or a download is explicitly approved.

