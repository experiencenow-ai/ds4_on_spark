# CUDA 13 + `sm_121` Notes

Spark0 reports compute capability `12.1`, which corresponds to `sm_121` in `nvcc`.

## Build Flags

For reproducible builds targeting GB10:

- Prefer `-arch=sm_121`, or
- Use explicit `-gencode arch=compute_121,code=sm_121` (and optionally add PTX).
- The probe `tools/cuda_probe/bin/cuda_sm121_fatbin_probe` is built via explicit `-gencode` and includes both `sm_120` + `sm_121` SASS plus `compute_121` PTX as a “portable fatbin” reference.

For convenience on single-GPU bring-up:

- `-arch=native` will compile for the visible GPU(s) detected by `nvcc` at build time.

## CUDA 13 `cudaDeviceProp` Layout Change

On Spark0’s CUDA 13.0 headers, `struct cudaDeviceProp` no longer includes fields like `clockRate`.

If you need clocks or other dynamic properties, use:

- `cudaDeviceGetAttribute(..., cudaDevAttrClockRate, ...)`
- `cudaDeviceGetAttribute(..., cudaDevAttrMemoryClockRate, ...)`

The `tools/cuda_probe/bin/cuda_device_props` probe is written to follow this pattern.

## Verifying `nvcc` Arch Mapping

`tools/cuda_probe/bin/cuda_sm121_arch_report` prints both:

- Runtime CC from `cudaGetDeviceProperties` (e.g. `12.1`)
- The compiled device macro `__CUDA_ARCH__` from a `-arch=sm_121` build (expected `1210`)

If your toolkit supports it, `nvcc --list-gpu-arch` and `nvcc --list-gpu-code` should include `compute_121` / `sm_121`.

## Separate Compilation / Device Link (`-rdc=true`)

Some CUDA codebases (and some build systems) rely on separate compilation and device linking (`nvlink`), especially when device functions span translation units.

The probe `tools/cuda_probe/bin/cuda_sm121_rdc_probe` is a tiny multi-translation-unit smoke test that builds via:

- `nvcc -dc` (relocatable device code objects)
- `nvcc -dlink` (device link step)
- final host link

If this probe fails to link for `sm_121`, treat it as a toolchain/blocker for any multi-file CUDA components (even if single-file `-arch=sm_121` probes compile and run).

Observed on Spark0 (2026-05-09): `rdc_probe in=0x12345678 out=0xb791f3de expect=0xb791f3de`.

## NVRTC JIT Compile For `compute_121`

Some stacks compile CUDA device code at runtime (NVRTC) and then load PTX via the CUDA Driver API.

The probe `tools/cuda_probe/bin/cuda_sm121_nvrtc_jit`:

- Calls `nvrtcGetSupportedArchs` and prints the supported virtual architectures (e.g. `80`, `90`, `100`, …).
- Compiles a tiny kernel with `--gpu-architecture=compute_121` to PTX via NVRTC.
- Loads the PTX with `cuModuleLoadDataEx` and launches the kernel, validating a minimal “NVRTC → PTX → Driver load → launch” path.

If this probe fails with `NVRTC_ERROR_INVALID_OPTION` or `NVRTC_ERROR_COMPILATION`, treat it as “NVRTC cannot target `compute_121` on this host/toolkit” even if `nvcc -arch=sm_121` works.

Observed on Spark0 (2026-05-09): `nvrtc supportedArchs` includes `121`, and the probe prints `nvrtc_jit ok`.

## nvcc Extended Lambda + Relaxed Constexpr Gate

Many CUTLASS/DeepGEMM-style codebases rely on `nvcc` accepting and correctly compiling with flags like:

- `--extended-lambda`
- `--expt-relaxed-constexpr`

The probe `tools/cuda_probe/bin/cuda_sm121_nvcc_flags_probe` is a tiny compile/run check that:

- builds for `-arch=sm_121` with `-std=c++20`
- uses a device lambda in a kernel (exercises `--extended-lambda`)
- runs a one-word sanity writeback (`0x12345679`)

Observed on Spark0 (2026-05-09): probe prints `nvcc_flags_probe ok out=0x12345679`.

## nvJitLink JIT Link For `sm_121` (PTX → CUBIN)

Some JIT pipelines compile CUDA source to PTX and then use nvJitLink to link PTX into an `sm_121` CUBIN before loading via the CUDA Driver API.

The probe `tools/cuda_probe/bin/cuda_sm121_nvjitlink_jit`:

- Compiles a tiny kernel to PTX via NVRTC (`--gpu-architecture=compute_121`)
- Uses nvJitLink (`-arch=sm_121`) to link PTX into a device CUBIN
- Loads the CUBIN with `cuModuleLoadDataEx` and launches the kernel, validating a minimal “NVRTC → PTX → nvJitLink → CUBIN → Driver load → launch” path

If this probe fails with `NVJITLINK_ERROR_MISSING_ARCH` or linker errors, treat it as “nvJitLink cannot target `sm_121` on this host/toolkit” even if `nvcc -arch=sm_121` works.

Observed on Spark0 (2026-05-09): probe prints `nvJitLinkVersion=13.0` and `nvjitlink_jit ok`.

## `sm_120` → `sm_121` Binary Compatibility Probe

Some upstream projects gate on `sm_120` (or have not yet added `sm_121`), so it is useful to know whether a binary compiled for `sm_120` runs correctly on GB10 (`sm_121`).

The probe `tools/cuda_probe/bin/cuda_sm120_compat_probe`:

- Compiles the kernel for `-arch=sm_120`
- Runs it on the visible device
- Prints the compiled `__CUDA_ARCH__` (expected `1200`) alongside the runtime device CC (expected `12.1` on Spark0)

If this probe succeeds on Spark0, it is a strong signal that “compile for `sm_120` and run on `sm_121`” is a workable short-term bridge for template libraries until they grow explicit `sm_121` support.

Observed on Spark0 (2026-05-09): device `cc=12.1`, probe prints `__CUDA_ARCH__=1200` and returns success.

## Shared Memory Opt-In (CUTLASS-style kernels)

Template GEMMs often rely on large dynamic shared-memory allocations gated by:

- `cudaDevAttrMaxSharedMemoryPerBlockOptin`
- `cudaFuncAttributeMaxDynamicSharedMemorySize` via `cudaFuncSetAttribute`

The probe `tools/cuda_probe/bin/cuda_sm121_smem_optin` prints the device limit and validates a launch that opts in to the reported maximum.

Observed on Spark0 (2026-05-08): `MaxSharedMemoryPerBlockOptin=101376` bytes.

## FP8 Header + Conversion Plumbing

DeepGEMM and some CUTLASS kernels depend on CUDA’s FP8 conversion helpers.

The probe `tools/cuda_probe/bin/cuda_sm121_fp8_conv` is a tiny compile/run check that:

- includes `cuda_fp8.h`
- converts a `float` to FP8 storage (`e4m3` and `e5m2`)
- converts back to `__half_raw` and prints the raw bits

## Pipeline memcpy-async (cp.async-style mainloops)

Many CUTLASS and custom GEMM kernels rely on CUDA pipeline primitives (cp.async-style) to move data from global memory into shared memory efficiently.

The probe `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async` is a tiny compile/run check that:

- includes `cuda_pipeline_primitives.h`
- issues a single `__pipeline_memcpy_async` from global->shared
- commits, waits, and copies the shared value back to global for verification

## CCCL Barrier + `cuda::memcpy_async` (CUTLASS-style staging)

CUDA 13 bundles CCCL (libcudacxx/thrust/cub) headers under `${CUDA_HOME}/include/cccl/`, and the high-level async-copy API lives under `<cuda/barrier>` / `cuda::memcpy_async`.

The probe `tools/cuda_probe/bin/cuda_sm121_barrier_memcpy_async` is a tiny compile/run check that:

- initializes a block-scope `cuda::barrier`
- issues a per-thread `cuda::memcpy_async(..., barrier)` global->shared copy
- waits via `barrier.arrive_and_wait()` and validates the copied values

## WMMA Tensor Core Smoke (CUTLASS-style proxy)

CUTLASS and other template GEMM libraries rely on tensor core matmul plumbing.

The probe `tools/cuda_probe/bin/cuda_sm121_wmma_smoke` is a tiny compile/run check that:

- includes `mma.h`
- runs a single warp WMMA matmul on `sm_121`
- prints a couple of output elements plus `max_abs_err` against an expected result

Observed on Spark0 (2026-05-09): `wmma_smoke ... max_abs_err=0`.

## Thread Block Clusters (CUTLASS-style scheduling)

Some newer templated kernels (including modern CUTLASS codepaths) can use thread-block clusters for scheduling and data movement.

The probe `tools/cuda_probe/bin/cuda_sm121_cluster_launch` is a tiny compile/run check that:

- queries `cudaDevAttrClusterLaunch` support
- uses `cudaLaunchKernelExC` + `cudaLaunchAttributeClusterDimension` to launch a 2-block cluster
- validates `cooperative_groups::this_cluster().block_rank()` via a device writeback

Observed on Spark0 (2026-05-09): `cluster_launch_supported=1`, `max_cluster_size_portable=8`, `max_active_clusters_for_2x1x1=48`.

## cuBLASLt FP8 Matmul Smoke

DeepGEMM and many CUTLASS kernels use FP8 inputs; a quick “works-first” gate is whether cuBLASLt can execute an FP8 GEMM on GB10.

The probes `tools/cuda_probe/bin/cuda_cublaslt_fp8_smoke` and `tools/cuda_probe/bin/cuda_cublaslt_fp8_e5m2_smoke` are tiny compile/run checks that:

- use FP8 E4M3 or E5M2 inputs for A/B (`CUDA_R_8F_E4M3` / `CUDA_R_8F_E5M2`)
- accumulates into FP32 (`CUBLAS_COMPUTE_32F`) and writes FP32 output
- uses default scale pointers (NULL ⇒ scale=1) to keep the API surface minimal

Observed on Spark0 (2026-05-09): `cuBLASLt fp8 e4m3 smoke max_abs_err_vs_one=0`.
Observed on Spark0 (2026-05-09): `cuda_cublaslt_fp8_e5m2_smoke` currently returns `CUBLAS_STATUS_NOT_SUPPORTED` (cuBLASLt heuristic selection fails).
