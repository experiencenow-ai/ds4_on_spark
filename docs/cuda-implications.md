# CUDA Probe Implications (DeepGEMM / CUTLASS / cuBLASLt)

This file records near-term engineering implications from the CUDA probe track.

## GB10 / Spark0 Baseline

From `docs/spark0-initial-probe.md` and the probe binaries in `tools/cuda_probe/`:

- Device is `NVIDIA GB10`, compute capability `12.1` (`sm_121`)
- CUDA toolkit is installed and `nvcc` works (CUDA 13.0 on Spark0)

## cuBLASLt

Implication:

- cuBLASLt should be treated as the “works-first” baseline for GEMM paths on GB10.
- When custom kernels or template libraries fail to build for `sm_121`, cuBLASLt is the fallback for correctness gating and early performance baselines.

Probe:

- `tools/cuda_probe/bin/cuda_cublaslt_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny matmul smoke test on Spark0.

## CUTLASS

Implication:

- CUTLASS is the most likely path for “bring-up on `sm_121`” when we need custom GEMMs beyond cuBLASLt.
- Any CUTLASS integration work must explicitly include `sm_121` in its arch list; do not assume `sm_100` build settings apply.

Next probe step:

- Verify a minimal CUTLASS example can compile for `sm_121` and run on Spark0 before committing to a larger CUTLASS-based kernel path.

## DeepGEMM

Implication:

- DeepGEMM’s upstream docs and headers appear to focus on SM90/SM100 paths; GB10 is `sm_121`.
- We should expect one of:
  - DeepGEMM fails fast on unknown `sm_121` and needs an upstream update or a local arch-spec patch, or
  - DeepGEMM falls back to a supported path with reduced performance/features.

Next probe step:

- Build and run the smallest DeepGEMM example on Spark0, capture exact failure mode, then decide whether to patch arch detection or switch to CUTLASS/cuBLASLt for the early kernels.
