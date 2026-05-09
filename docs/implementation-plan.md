# Implementation Plan

## Review Summary

The draft design has the right shape: a narrow DeepSeek V4 Flash engine for
DGX Spark, token-ID disk KV reuse, 2-Spark first, and correctness-gated kernel
work. The main change is sequencing. Native FP4 kernels, MTP, and expert queues
should follow measured baselines, not lead the project.

Key risks:

- DeepGEMM is highly relevant, but its published quick-start targets SM90/SM100.
  GB10/Spark compatibility must be measured directly.
- Spark stacking uses Ethernet-configured CX-7 links with NCCL. Do not assume
  datacenter RDMA/NVLink latency.
- DeepSeek V4 architecture details are nontrivial: sliding attention, CSA, HCA,
  mHC residual streams, hash-MoE bootstrap layers, and specific cache layers all
  need a source-derived contract.
- MTP is an experiment until acceptance rate and end-to-end speedup are measured.
- Expert queues may duplicate or interfere with DeepGEMM Mega MoE style kernels.
  Build only if profiling shows decode underfills expert GEMMs.

## N-Step Plan

N = 19.

1. Bootstrap repository and upstream references.
2. Hardware acceptance on Spark: OS, driver, CUDA, device props, clocks,
   thermals, memory bandwidth, and FP4 capability.
3. Spark networking acceptance: Mac/Spark reachability, SSH keys, CX-7 path,
   and NCCL smoke tests.
4. Existing runtime baseline: antirez GGUF / llama.cpp Spark path on one Spark.
5. Quantized single-Spark milestone: produce tokens on Spark0 with the smallest
   credible V4 Flash quantized artifact and a V4-capable external runtime.
6. Artifact inventory: official safetensors, native FP4/FP8 GGUF, antirez q2/q4
   GGUF, MTP artifact.
7. Model contract: tensor names, shapes, quant formats, tokenizer, encoding,
   cache structures, and layer schedule.
8. Correctness oracle: official Python/Transformers logits and trace fixtures
   for short, medium, and long contexts.
9. Build skeleton: C/CUDA project, static allocator, config, logging, tests,
   CUDA error wrappers.
10. Loader track: GGUF first for antirez path, official FP4/FP8 loader second.
11. API/server track: OpenAI/Anthropic endpoints, DSML/tool rendering, streaming.
12. Single-Spark q2 CUDA baseline with no scheduler innovation.
13. Attention/cache track: implement V4 sliding/CSA/HCA caches exactly.
14. Kernel spike: DeepGEMM FP8/FP4, Mega MoE, cuBLASLt, CUTLASS, Flash attention.
15. Native FP4/FP8 single-Spark or sharded-load proof.
16. Dual-Spark TP=2: launch, rank setup, split routed experts, collectives,
    per-rank KV/checkpoint layout.
17. Continuous batching scheduler: interactive/background lanes, backpressure,
    metrics, no MTP yet.
18. Optimization experiments: adaptive MTP first, expert queues second.
19. Production hardening: disk KV, watchdogs, Prometheus, tracing, systemd,
    72-hour soak.

## Parallel Tracks

Track A: Hardware and networking.

- Owns steps 2 and 3.
- Output: Spark probe report, network map, NCCL baseline.

Track B: Upstream and model contract.

- Owns steps 4, 5, 6, 7, and 8.
- Output: contract docs, oracle fixtures, validated source links.

Track C: Engine skeleton and API.

- Owns steps 9, 10, and 11.
- Output: buildable repo, loader skeleton, API compatibility harness.

Track D: CUDA correctness.

- Owns steps 12 and 13.
- Output: single-Spark q2 path matching oracle.

Track E: Kernel performance.

- Owns step 14.
- Output: GB10 kernel compatibility matrix and shape benchmarks.

Track F: Distributed TP.

- Owns steps 15 and 16.
- Output: dual-Spark proof with measured collective cost.

Track G: Scheduler and serving.

- Owns step 17.
- Output: continuous batching with observability.

Track H: Optimization and production.

- Owns steps 18 and 19.
- Output: measured optimizations, soak-tested deployment.

## First Gate

Before writing custom inference code, produce:

- Spark hardware probe output.
- `nvidia-smi` / CUDA / NCCL version data.
- One existing baseline run, even if slow.
- One quantized single-Spark V4 Flash smoke attempt, successful or with an exact
  runtime/artifact failure report.
- DeepGEMM build/run result on GB10.
- Model contract draft from official source/config files.
