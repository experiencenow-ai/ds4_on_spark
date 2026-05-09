# CUDA Probe Implications (DeepGEMM / CUTLASS / cuBLASLt)

This file records near-term engineering implications from the CUDA probe track.

## GB10 / Spark0 Baseline

From `docs/spark0-initial-probe.md` and the probe binaries in `tools/cuda_probe/`:

- Device is `NVIDIA GB10`, compute capability `12.1` (`sm_121`)
- CUDA toolkit is installed and `nvcc` works (CUDA 13.0 on Spark0)
- `nvcc --list-gpu-arch` / `nvcc --list-gpu-code` should include `compute_121` / `sm_121` when supported by the toolkit
- `tools/cuda_probe/bin/cuda_sm121_arch_report` prints runtime CC + compiled `__CUDA_ARCH__` (observed `1210` for `sm_121`)
- `tools/cuda_probe/bin/cuda_sm120_compat_probe` shows that an `sm_120`-compiled kernel runs successfully on GB10 (`sm_121`) (observed `__CUDA_ARCH__=1200` on device `cc=12.1`)
- `tools/cuda_probe/bin/cuda_sm121_smem_optin` prints `cudaDevAttrMaxSharedMemoryPerBlockOptin` and validates an opt-in dynamic shared-memory launch
  - Observed on Spark0 (2026-05-08): `MaxSharedMemoryPerBlockOptin=101376` bytes
- `tools/cuda_probe/bin/cuda_sm121_devattrs` dumps key `cudaDeviceGetAttribute` values commonly used to gate kernel bring-up (shared memory, registers, L2).
- `tools/cuda_probe/bin/cuda_sm121_fp8_conv` validates that CUDA 13 FP8 conversion helpers (`cuda_fp8.h`) compile and run for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async` validates that CUDA pipeline primitives (`__pipeline_memcpy_async` / cp.async-style) compile and run for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_cxx20_probe` validates that `nvcc` + the host toolchain can compile C++20 (`-std=c++20`) for `sm_121` (DeepGEMM-style build gate).
- `tools/cuda_probe/bin/cuda_sm121_nvcc_flags_probe` validates that `nvcc` accepts common template-kernel compile flags (`--extended-lambda` + `--expt-relaxed-constexpr`) with `-std=c++20` for `sm_121` (CUTLASS/DeepGEMM-style compile gate).
- `tools/cuda_probe/bin/cuda_sm121_rdc_probe` validates that `nvcc` + `nvlink` can perform separate compilation (`-dc`) + device link (`-dlink`) for `sm_121` (multi-translation-unit CUDA build gate; observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_cccl_atomic_ref` validates CCCL atomics (`cuda::atomic_ref`) compile and run for `sm_121` (template-kernel plumbing dependency).
- `tools/cuda_probe/bin/cuda_sm121_cuda_graph_smoke` validates CUDA graph stream capture → instantiate → launch on `sm_121` (CUDAGraph-style execution gate).
- `tools/cuda_probe/bin/cuda_sm121_nvrtc_jit` validates an NVRTC “compile to PTX for `compute_121` → load via Driver API → launch kernel” path; this is a useful gate for any JIT compilation flows on GB10 (observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_nvjitlink_jit` validates an NVRTC+nvJitLink “compile to PTX for `compute_121` → link to `sm_121` CUBIN → load via Driver API → launch kernel” path; this is a useful gate for JIT flows that rely on nvJitLink (observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_wmma_smoke` validates that WMMA (`mma.h`) tensor core matmul plumbing compiles and runs for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_cluster_launch` validates that thread-block cluster launches (`cudaLaunchKernelExC` + `cudaLaunchAttributeClusterDimension`) and `cooperative_groups::this_cluster()` compile and run for `sm_121` (observed on Spark0: `cluster_launch_supported=1`, `max_cluster_size_portable=8`).

## cuBLASLt

Implication:

- cuBLASLt should be treated as the “works-first” baseline for GEMM paths on GB10.
- When custom kernels or template libraries fail to build for `sm_121`, cuBLASLt is the fallback for correctness gating and early performance baselines.
- FP8 matmul is verified via cuBLASLt on `sm_121` for E4M3 (see `cuda_cublaslt_fp8_smoke`), which de-risks early FP8 bring-up for DeepGEMM-style paths.
- The current CUDA 13.0 (`V13.0.88`) cuBLASLt stack on Spark0 returns `CUBLAS_STATUS_NOT_SUPPORTED` for the E5M2 smoke probe (`cuda_cublaslt_fp8_e5m2_smoke`) even when trying multiple `cublasComputeType_t` variants (observed `cublasLtGetVersion=130101`), which may matter for DeepGEMM paths that use E5M2 inputs.

Probe:

- `tools/cuda_probe/bin/cuda_cublaslt_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny matmul smoke test on Spark0.
- `tools/cuda_probe/bin/cuda_cublaslt_fp8_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny FP8 (E4M3) matmul smoke test on Spark0.
- `tools/cuda_probe/bin/cuda_cublaslt_fp8_e5m2_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny FP8 (E5M2) matmul smoke test on Spark0.

## CUTLASS

Implication:

- CUTLASS is the most likely path for “bring-up on `sm_121`” when we need custom GEMMs beyond cuBLASLt.
- Any CUTLASS integration work must explicitly include `sm_121` in its arch list; do not assume `sm_100` build settings apply.
- If `sm_121` is not available in a given upstream build system yet, validate whether building for `sm_120` runs correctly on GB10 first (see `cuda_sm120_compat_probe` below).

Next probe step:

- Verify a minimal CUTLASS example can compile for `sm_121` and run on Spark0 before committing to a larger CUTLASS-based kernel path.
- Run `tools/cuda_probe/bin/cuda_sm120_compat_probe` on Spark0 to establish whether `sm_120` SASS is a viable short-term compatibility target for GB10.
- Confirm the required shared-memory footprint fits within `cudaDevAttrMaxSharedMemoryPerBlockOptin` for any CUTLASS kernels we plan to bring up.
- Confirm that pipeline primitives (cp.async-style global->shared copies) work on GB10; see `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async`.
- Confirm that tensor core matmul plumbing works on GB10; see `tools/cuda_probe/bin/cuda_sm121_wmma_smoke`.
- Confirm that cluster launches and cluster intrinsics work on GB10; see `tools/cuda_probe/bin/cuda_sm121_cluster_launch`.
- Note: this repo’s pinned DeepGEMM upstream uses a CUTLASS submodule; we intentionally do not auto-init submodules in the probe loop (see `docs/upstream-deepgemm.md`), so a CUTLASS compile/run probe requires an explicit submodule init (extra downloads).

## Build Portability Notes (CUDA 13)

Implication:

- `-arch=native` is convenient for single-host bring-up, but `nvcc` generates SASS for the visible GPU(s) and (per CUDA 13 `nvcc` docs) does not embed PTX; this is not ideal for “ship one binary and run anywhere”.
- For artifacts expected to run across multiple GPU variants, prefer explicit `-gencode` with both SASS and PTX (for example: `arch=compute_121,code=sm_121,compute_121`) and add additional `sm_*` entries as needed for your fleet.
- `tools/cuda_probe/bin/cuda_sm121_fatbin_probe` is a tiny “fatbin portability” gate that builds via `-gencode` (includes `sm_120` + `sm_121` SASS and `compute_121` PTX) and runs the same sanity kernel as the `-arch=sm_121` probe.

## DeepGEMM

Implication:

- DeepGEMM’s upstream docs and headers appear to focus on SM90/SM100 paths; GB10 is `sm_121`.
- We should expect one of:
  - DeepGEMM fails fast on unknown `sm_121` and needs an upstream update or a local arch-spec patch, or
  - DeepGEMM falls back to a supported path with reduced performance/features.
 - DeepGEMM requires C++20; use `tools/cuda_probe/bin/cuda_sm121_cxx20_probe` as the first gate before pulling upstream code.

Next probe step:

- Build and run the smallest DeepGEMM example on Spark0, capture exact failure mode, then decide whether to patch arch detection or switch to CUTLASS/cuBLASLt for the early kernels.
- Run `tools/cuda_probe/bin/cuda_sm120_compat_probe` to determine whether `sm_120`-targeted build artifacts are likely to run on GB10 (useful when upstream build scripts have not added `sm_121` yet).
- Confirm that `cuda_fp8.h` conversion helpers compile and run on GB10 (DeepGEMM uses FP8 paths); see `tools/cuda_probe/bin/cuda_sm121_fp8_conv`.
- Confirm that pipeline primitives (cp.async-style mainloop plumbing) compile and run on GB10; see `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async`.
- If DeepGEMM depends on large dynamic shared memory, use `cuda_sm121_smem_optin` output as the initial feasibility gate before deeper porting work.
- If DeepGEMM is blocked on missing submodules, use `cuda_sm121_devattrs` to record the baseline device limits and features while deciding whether to pull CUTLASS into the tree.
