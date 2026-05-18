# DS4 External MTP Runtime Bench

Status: standard vLLM release is installed on Spark1/Spark2; no external DS4
MTP speed result yet because the HF checkpoint is not staged.

Run: `ds4-external-mtp-runtime-bench-spark0-20260517`

Artifact: `fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark0_20260517.example.json`

Latest Spark1/Spark2 readiness run:
`ds4-external-mtp-runtime-bench-spark12-vllm-readiness-20260518`

Artifact:
`fixtures/external_mtp_runtime_bench/ds4_external_mtp_runtime_bench_spark12_vllm_readiness_20260518.example.json`

## Result

| Runtime | DS4 MTP result | Blocker |
| --- | --- | --- |
| llama.cpp | failed before generation | Upstream MTP build exposes `--spec-type draft-mtp`, but cannot load the DS4 GGUF: `unknown model architecture: 'deepseek4'`. Latest upstream has MTP code but no `deepseek4`; the DS4 fork has `deepseek4` but not the upstream MTP runtime. |
| SGLang | not run | Spark1/Spark2 Docker access is permission-denied for the Spark users and SGLang is not installed. Official DeepSeek-V4-Flash recipes document 4-GPU Blackwell for the unmodified checkpoint; keep SGLang as the second external runtime after vLLM model-load evidence. |
| vLLM | readiness passed, benchmark blocked | Upstream vLLM `0.21.0` installs on both Spark1 and Spark2, imports with Torch `2.11.0+cu130`, exposes `DeepseekV4ForCausalLM` and `DeepSeekV4MTPModel`, and a temporary Ray `2.54.0` cluster over `10.10.5.1`/`10.10.5.2` saw `GPU=2.0` with two GB10 resources. The remaining blocker is staging the vLLM-compatible `deepseek-ai/DeepSeek-V4-Flash` HF checkpoint (`148.66 GiB` safetensors) and running the TP=2 baseline/MTP benchmark. |

## Decision

Use upstream vLLM as the next standard-runtime path on Spark1/Spark2. This is
not yet a throughput result and must not be treated as MTP speedup evidence.

Exact next unblocks:

1. Stage `deepseek-ai/DeepSeek-V4-Flash` on Spark1/Spark2 or a shared
   filesystem and verify the safetensors footprint/hash.
2. Start Ray with Spark1 as head on `10.10.5.1` and Spark2 as worker on
   `10.10.5.2`.
3. Run vLLM TP=2 target-only, then MTP with
   `--speculative-config '{"method":"mtp","num_speculative_tokens":1}'`.
4. Record baseline t/s, MTP t/s, acceptance counters, and blocker detail in the
   external runtime artifact before making any routing decision.
