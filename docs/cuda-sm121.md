# CUDA 13 + `sm_121` Notes

Spark0 reports compute capability `12.1`, which corresponds to `sm_121` in `nvcc`.

## Build Flags

For reproducible builds targeting GB10:

- Prefer `-arch=sm_121`, or
- Use explicit `-gencode arch=compute_121,code=sm_121` (and optionally add PTX).

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
