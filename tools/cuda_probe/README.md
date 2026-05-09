# CUDA Probe Tools

Tiny CUDA compile/run probes for DGX Spark (GB10) acceptance work.

## Build (on Spark0)

```bash
cd tools/cuda_probe
make
```

Expected outputs:

- `tools/cuda_probe/bin/cuda_device_props`: print basic device/runtime info.
- `tools/cuda_probe/bin/cuda_sm121_probe`: compile/run sanity kernel for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_arch_report`: print runtime CC + compiled `__CUDA_ARCH__`.
- `tools/cuda_probe/bin/cuda_sm120_compat_probe`: compile for `sm_120` and run on the device; tests `sm_120`→`sm_121` compatibility.
- `tools/cuda_probe/bin/cuda_cublaslt_smoke`: link/run tiny cuBLASLt matmul for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_smem_optin`: print `MaxSharedMemoryPerBlockOptin` and run a dynamic shared-memory launch.
- `tools/cuda_probe/bin/cuda_sm121_devattrs`: dump CUTLASS/DeepGEMM-relevant `cudaDeviceGetAttribute` values.
- `tools/cuda_probe/bin/cuda_sm121_fp8_conv`: compile/run FP8 conversion plumbing via `cuda_fp8.h`.
- `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async`: compile/run a `__pipeline_memcpy_async` (cp.async-style) copy from global->shared.
- `tools/cuda_probe/bin/cuda_sm121_barrier_memcpy_async`: compile/run `cuda::memcpy_async(..., barrier)` using CCCL’s `<cuda/barrier>` API.

## Run

```bash
./tools/cuda_probe/bin/cuda_device_props
./tools/cuda_probe/bin/cuda_sm121_probe
./tools/cuda_probe/bin/cuda_sm121_arch_report
./tools/cuda_probe/bin/cuda_sm120_compat_probe
./tools/cuda_probe/bin/cuda_cublaslt_smoke
./tools/cuda_probe/bin/cuda_sm121_smem_optin
./tools/cuda_probe/bin/cuda_sm121_devattrs
./tools/cuda_probe/bin/cuda_sm121_fp8_conv
./tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async
./tools/cuda_probe/bin/cuda_sm121_barrier_memcpy_async
```

## Notes

- `cuda_sm121_probe` compiles for `-arch=sm_121` and should fail fast if `nvcc`
  or the installed toolkit does not recognize `sm_121`.
- `cuda_cublaslt_smoke` is a minimal “link + run” check for `-lcublasLt` on
  `sm_121`.
- `cuda_sm120_compat_probe` is a minimal “run an `sm_120`-compiled kernel on the device” check; if it succeeds on Spark0, it suggests `sm_120` SASS is a viable short-term compatibility target for GB10 (`sm_121`) (observed success on 2026-05-09).
- `cuda_sm121_smem_optin` is an opt-in shared-memory sanity check used by
  CUTLASS-style kernels that rely on `cudaFuncAttributeMaxDynamicSharedMemorySize`.
- `cuda_sm121_devattrs` records device limits and runtime feature gates that commonly gate
  CUTLASS / custom GEMM kernel bring-up.
- `cuda_sm121_fp8_conv` is a compile/run check for CUDA’s FP8 conversion helpers.
- `cuda_sm121_pipeline_memcpy_async` is a compile/run check for CUDA pipeline primitives (`cuda_pipeline_primitives.h`) used by cp.async-style kernels.
- `cuda_sm121_barrier_memcpy_async` is a compile/run check for CCCL’s higher-level `cuda::barrier` + `cuda::memcpy_async` API (commonly used by templated kernels).
- These probes intentionally keep dependencies tiny and print errors verbatim so
  failures can be pasted into an issue/PR.
