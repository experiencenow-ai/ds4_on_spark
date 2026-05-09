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
- `tools/cuda_probe/bin/cuda_cublaslt_smoke`: link/run tiny cuBLASLt matmul for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_smem_optin`: print `MaxSharedMemoryPerBlockOptin` and run a dynamic shared-memory launch.
- `tools/cuda_probe/bin/cuda_sm121_devattrs`: dump CUTLASS/DeepGEMM-relevant `cudaDeviceGetAttribute` values.

## Run

```bash
./tools/cuda_probe/bin/cuda_device_props
./tools/cuda_probe/bin/cuda_sm121_probe
./tools/cuda_probe/bin/cuda_sm121_arch_report
./tools/cuda_probe/bin/cuda_cublaslt_smoke
./tools/cuda_probe/bin/cuda_sm121_smem_optin
./tools/cuda_probe/bin/cuda_sm121_devattrs
```

## Notes

- `cuda_sm121_probe` compiles for `-arch=sm_121` and should fail fast if `nvcc`
  or the installed toolkit does not recognize `sm_121`.
- `cuda_cublaslt_smoke` is a minimal “link + run” check for `-lcublasLt` on
  `sm_121`.
- `cuda_sm121_smem_optin` is an opt-in shared-memory sanity check used by
  CUTLASS-style kernels that rely on `cudaFuncAttributeMaxDynamicSharedMemorySize`.
- `cuda_sm121_devattrs` records device limits and runtime feature gates that commonly gate
  CUTLASS / custom GEMM kernel bring-up.
- Both probes intentionally keep dependencies tiny and print errors verbatim so
  failures can be pasted into an issue/PR.
