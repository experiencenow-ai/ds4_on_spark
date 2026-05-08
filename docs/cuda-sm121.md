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

## Shared Memory Opt-In (CUTLASS-style kernels)

Template GEMMs often rely on large dynamic shared-memory allocations gated by:

- `cudaDevAttrMaxSharedMemoryPerBlockOptin`
- `cudaFuncAttributeMaxDynamicSharedMemorySize` via `cudaFuncSetAttribute`

The probe `tools/cuda_probe/bin/cuda_sm121_smem_optin` prints the device limit and validates a launch that opts in to the reported maximum.

Observed on Spark0 (2026-05-08): `MaxSharedMemoryPerBlockOptin=101376` bytes.
