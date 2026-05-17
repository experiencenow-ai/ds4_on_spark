# DS4 External MTP Runtime Bench

Status: blocked, no external DS4 MTP speed result yet.

Run: `ds4-external-mtp-runtime-bench-spark0-20260517`

Artifact: `fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark0_20260517.example.json`

## Result

| Runtime | DS4 MTP result | Blocker |
| --- | --- | --- |
| llama.cpp | failed before generation | Upstream MTP build exposes `--spec-type draft-mtp`, but cannot load the DS4 GGUF: `unknown model architecture: 'deepseek4'`. Latest upstream has MTP code but no `deepseek4`; the DS4 fork has `deepseek4` but not the upstream MTP runtime. |
| SGLang | not run | Spark0 has no SGLang install or HF DeepSeek-V4-Flash checkpoint; Docker access is denied for the Spark user; Spark1/Spark2 are unreachable; official DS4 Flash recipe is 4-GPU Blackwell. |
| vLLM | not run | Spark0 has no vLLM install or HF DeepSeek-V4-Flash checkpoint. vLLM has a DeepSeek-V4 MTP model path, but our available artifact is GGUF. |

## Decision

Do not switch runtimes yet. There is no out-of-box external DS4 MTP result on the currently reachable hardware.

Exact next unblocks:

1. Make Spark1/Spark2 reachable and stage the HF DeepSeek-V4-Flash checkpoint, then run SGLang/vLLM server benchmarks.
2. Or merge upstream llama.cpp MTP into the DS4 `deepseek4` fork and rerun the GGUF + MTP sidecar benchmark.
