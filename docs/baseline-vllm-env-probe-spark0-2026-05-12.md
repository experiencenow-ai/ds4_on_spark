# Baseline: Spark0 vLLM environment probe (no-download)

Date (UTC): 2026-05-12T15:03:38Z

Baseline type:

- [ ] antirez/ds4 (Mac / Metal)
- [ ] llama.cpp (Spark / CUDA)
- [x] vLLM (Spark / reference)
- [ ] Ling 2.6 Flash target-only (Spark / vLLM or SGLang)
- [ ] Qwen target-only (Spark / vLLM or SGLang)
- [ ] Qwen + DFlash draft (Spark / speculative)
- [ ] other target + DFlash draft (Spark / speculative)
- [ ] ds4_on_spark (future)

Purpose: record Spark0 environment readiness for vLLM-based Ling/Qwen/DFlash baselines without downloading any model weights.

## Host

- Hostname: `aitopatom-9ab9` (Spark0)
- OS / kernel: `Linux 6.17.0-1014-nvidia` (aarch64)
- GPU: NVIDIA GB10 (CUDA 13.0 / driver 580.142)
- Python: `/usr/bin/python3` (`Python 3.12.3`)

## Repo Revision

- ds4_on_spark commit: `dbfaa05154d70d31ae830b8ac3645d33cd78ebcc`

## Command Line

Mac → Spark (no generation; no fetch):

```sh
OUT_ROOT=/private/tmp/ds4_on_spark_baseline_probes \
RUN_LABEL=vllm-env-probe \
REMOTE_VLLM_ENV='ALLOW_RUN=0' \
scripts/run_baseline_vllm_env_probe.sh spark0@aitopatom-9ab9.local
```

Local runner output dir (not committed): `/private/tmp/ds4_on_spark_baseline_probes/20260512T150337Z-vllm-env-probe`

## Results

Environment probe:

- `vllm` package: missing (`pip show vllm` not found)
- `torch` package: missing (`pip show torch` not found)
- Torch CUDA probe: failed (`No module named 'torch'`)

Run outcome:

- Exit code: `0` (probe completed)
- Model generation: skipped (`ALLOW_RUN=0`)
- Weight downloads: none (explicitly blocked)

Next step:

- Ling/Qwen target-only and DFlash paired baselines are blocked until Spark0 has a vLLM-capable runtime (container or install). Installing vLLM/torch or pulling a large container must be explicitly approved before running.

