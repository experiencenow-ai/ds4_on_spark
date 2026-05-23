# Implementation Plan

> Supersedes: `docs/implementation-plan.md`

This is a canonical document. Update this file instead of adding overlapping docs.

## Review Summary

The draft design has the right shape: a narrow DeepSeek V4 Flash engine for
DGX Spark, token-ID disk KV reuse, 2-Spark first, and correctness-gated kernel
work. The main change is sequencing. A working quantized V4 Flash runtime on one
Spark can become the near-term high-performance path: instrument it, add expert
queueing when real route traces justify it, and test MTP against a real decode
loop before waiting for the native DS4 loader.

Key risks:

- DeepGEMM is highly relevant, but its published quick-start targets SM90/SM100.
  GB10/Spark compatibility must be measured directly.
- Spark stacking uses Ethernet-configured CX-7 links with NCCL. Do not assume
  datacenter RDMA/NVLink latency.
- DeepSeek V4 architecture details are nontrivial: sliding attention, CSA, HCA,
  mHC residual streams, hash-MoE bootstrap layers, and specific cache layers all
  need a source-derived contract.
- MTP is an experiment until acceptance rate and end-to-end speedup are measured,
  but it should be tested as soon as the quantized runtime can expose draft
  tokens/logits.
- Expert queues may duplicate or interfere with runtime MoE batching. Build only
  after quantized-runtime traces show decode underfills expert GEMMs or hot
  experts create avoidable idle gaps.

## N-Step Plan

N = 20.

1. Bootstrap repository and upstream references.
2. Hardware acceptance on Spark: OS, driver, CUDA, device props, clocks,
   thermals, memory bandwidth, and FP4 capability.
3. Spark networking acceptance: Mac/Spark reachability, SSH keys, CX-7 path,
   and NCCL smoke tests.
4. Existing runtime baseline: antirez GGUF / llama.cpp Spark path on one Spark.
5. Quantized single-Spark milestone: produce tokens on Spark0 with the smallest
   credible V4 Flash quantized artifact and a V4-capable external runtime.
6. Quantized performance path: instrument the working runtime, collect real
   routing traces, and test expert queueing plus MTP before native DS4 parity.
7. Artifact inventory: official safetensors, native FP4/FP8 GGUF, antirez q2/q4
   GGUF, MTP artifact.
8. Model contract: tensor names, shapes, quant formats, tokenizer, encoding,
   cache structures, and layer schedule.
9. Correctness oracle: official Python/Transformers logits and trace fixtures
   for short, medium, and long contexts.
10. Build skeleton: C/CUDA project, static allocator, config, logging, tests,
   CUDA error wrappers.
11. Loader track: GGUF first for antirez path, official FP4/FP8 loader second.
12. API/server track: OpenAI/Anthropic endpoints, DSML/tool rendering, streaming.
13. Native single-Spark q2/FP4 correctness path with no scheduler innovation.
14. Attention/cache track: implement V4 sliding/CSA/HCA caches exactly.
15. Kernel spike: DeepGEMM FP8/FP4, Mega MoE, cuBLASLt, CUTLASS, Flash attention.
16. Native FP4/FP8 single-Spark or sharded-load proof.
17. Dual-Spark TP=2: launch, rank setup, split routed experts, collectives,
    per-rank KV/checkpoint layout.
18. Continuous batching scheduler: interactive/background lanes, backpressure,
    and metrics, using quantized-runtime traces when available.
19. Optimization experiments: adaptive MTP and expert queues, first on the
    quantized path and then in native DS4 once the hooks are proven.
20. Production hardening: disk KV, watchdogs, Prometheus, tracing, systemd,
    72-hour soak.

## Parallel Tracks

Track A: Hardware and networking.

- Owns steps 2 and 3.
- Output: Spark probe report, network map, NCCL baseline.

Track B: Upstream and model contract.

- Owns steps 4, 5, 6, 7, 8, and 9.
- Output: contract docs, oracle fixtures, validated source links.

Track C: Engine skeleton and API.

- Owns steps 10, 11, and 12.
- Output: buildable repo, loader skeleton, API compatibility harness.

Track D: CUDA correctness.

- Owns steps 13 and 14.
- Output: single-Spark q2 path matching oracle.

Track E: Kernel performance.

- Owns step 15.
- Output: GB10 kernel compatibility matrix and shape benchmarks.

Track F: Distributed TP.

- Owns steps 16 and 17.
- Output: dual-Spark proof with measured collective cost.

Track G: Scheduler and serving.

- Owns step 18.
- Output: continuous batching with observability.

Track H: Optimization and production.

- Owns steps 19 and 20.
- Output: measured optimizations, soak-tested deployment.

## First Gate

Before writing custom inference code, produce:

- Spark hardware probe output.
- `nvidia-smi` / CUDA / NCCL version data.
- One existing baseline run, even if slow.
- One quantized single-Spark V4 Flash smoke attempt, successful or with an exact
  runtime/artifact failure report.
- A decision on whether the quantized runtime exposes enough hooks for expert
  queueing and MTP experiments.
- DeepGEMM build/run result on GB10.
- Model contract draft from official source/config files.
