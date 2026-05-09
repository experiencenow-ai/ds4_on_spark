# CUDA Probe Track

This track keeps probe-only CUDA snippets that answer: “Can we compile for and run on GB10 (CC 12.1 / `sm_121`) with the installed CUDA toolkit?”

## Spark0: Compile + Run

From the Mac (this repo checkout):

```bash
./scripts/cuda_probe_spark0.sh
```

What it does:

- Ships `tools/cuda_probe/` to Spark0 (no remote git clone required).
- Builds with `/usr/local/cuda/bin/nvcc`.
- Runs:
  - `cuda_device_props_tiny` (one-line runtime + device summary)
  - `cuda_device_props` (runtime + device properties)
  - `cuda_sm121_probe` (sanity kernel compiled for `sm_121`)
  - `cuda_sm121_arch_report` (prints device CC + compiled `__CUDA_ARCH__`)
  - `cuda_sm120_compat_probe` (runs an `sm_120`-compiled kernel on the device; tests `sm_120`→`sm_121` compatibility)
  - `cuda_cublaslt_smoke` (tiny cuBLASLt matmul smoke test)
  - `cuda_cublaslt_fp8_smoke` (tiny cuBLASLt FP8 (E4M3) matmul smoke test)
  - `cuda_sm121_smem_optin` (shared-memory opt-in + dynamic shared memory launch)
  - `cuda_sm121_devattrs` (device attribute dump for kernel bring-up gating)
  - `cuda_sm121_fp8_conv` (`cuda_fp8.h` conversion probe for FP8 plumbing)
  - `cuda_sm121_pipeline_memcpy_async` (`__pipeline_memcpy_async` global->shared copy probe)
  - `cuda_sm121_barrier_memcpy_async` (`cuda::barrier` + `cuda::memcpy_async` copy probe)
  - `cuda_sm121_cccl_atomic_ref` (CCCL `cuda::atomic_ref` device-scope + block-scope atomics)
  - `cuda_sm121_cxx20_probe` (`-std=c++20` toolchain probe; DeepGEMM-style build gate)
  - `cuda_sm121_wmma_smoke` (`mma.h` WMMA matmul smoke test; CUTLASS-style proxy)
  - `cuda_sm121_cluster_launch` (thread-block cluster launch + `cooperative_groups::this_cluster().block_rank()` smoke test)

Environment overrides:

- `SSH_OPTS`: forwarded to `ssh`
- `REMOTE_DIR`: where the probe directory lands on Spark0 (default: `/tmp/ds4_cuda_probe`)

## Spark0: Compile-Only `sm_121`

```bash
./scripts/cuda_probe_compile_only_spark0.sh
```

This is useful when kernel run is blocked but `nvcc` behavior needs confirmation.
It prints `nvcc --list-gpu-arch` / `nvcc --list-gpu-code` when supported, then compiles `cuda_sm121_compile_probe.o`, `cuda_sm121_probe`, `cuda_sm121_arch_report`, `cuda_cublaslt_smoke`, `cuda_cublaslt_fp8_smoke`, `cuda_sm121_smem_optin`, `cuda_sm121_devattrs`, `cuda_sm121_fp8_conv`, `cuda_sm121_pipeline_memcpy_async`, `cuda_sm121_barrier_memcpy_async`, `cuda_sm121_cccl_atomic_ref`, `cuda_sm121_cxx20_probe`, and `cuda_sm121_wmma_smoke` for `sm_121`, plus `cuda_sm120_compat_probe` for `sm_120`.

## Current Spark0 Results (2026-05-09)

Commands run:

```bash
./scripts/cuda_probe_compile_only_spark0.sh
./scripts/cuda_probe_spark0.sh
```

Observed:

- `nvcc` is CUDA 13.0 (`V13.0.88`)
- `-arch=sm_121` compiles and links (including `-lcublasLt`)
- `-arch=sm_120` binaries run on GB10 (`sm_121`) successfully (probe prints `__CUDA_ARCH__=1200` on device `cc=12.1`)
- Runtime launches a tiny `sm_121` kernel successfully
- cuBLASLt matmul smoke test succeeds (`max_abs_err=0`)
- cuBLASLt FP8 matmul smoke test succeeds (`max_abs_err_vs_one=0`)
- Shared-memory opt-in probe succeeds; `MaxSharedMemoryPerBlockOptin=101376` bytes on GB10
- FP8 conversion probe succeeds (`fp8_conv ... halfraw_e4m3=0x3d00`)
- Pipeline memcpy-async probe succeeds (cp.async-style global->shared copy)
- Barrier memcpy-async probe succeeds (`cuda::barrier` + `cuda::memcpy_async`)
- CCCL atomic-ref probe succeeds (`cuda::atomic_ref`)
- C++20 toolchain probe succeeds (`-std=c++20`)
- WMMA matmul smoke test succeeds (`wmma_smoke ... max_abs_err=0`)
- Cluster launch probe succeeds (`cluster_block_rank out[0]=0 out[1]=1`)
- Device is reported as `NVIDIA GB10` with `cc=12.1`

Selected output excerpt:

```text
cudaDriverGetVersion=13000 cudaRuntimeGetVersion=13000
cudaGetDeviceCount=1
device[0]=NVIDIA GB10 cc=12.1 clock_khz=2418000 mem=128518373376
kernel wrote 0xc0d3cafe
kernel wrote magic=0xc0d3cafe __CUDA_ARCH__=1210
expect: compiled __CUDA_ARCH__=1200 for -arch=sm_120
kernel wrote magic=0xc0d3cafe __CUDA_ARCH__=1200
cuBLASLt sgemm smoke max_abs_err=0
cuBLASLt fp8 e4m3 smoke max_abs_err_vs_one=0
max_smem_per_block_optin_bytes=101376
smem probe wrote 0x000000a5
fp8_conv x=1.250000 e4m3=0x3a e5m2=0x3d halfraw_e4m3=0x3d00 halfraw_e5m2=0x3d00
pipeline_memcpy_async out=11111111 22222222 33333333 44444444
barrier_memcpy_async ok first=decaf000 last=decaf01f
wmma_smoke C00=16.000000 C255=16.000000 max_abs_err=0.000000
cluster_launch_supported=1
max_cluster_size_portable=8
max_active_clusters_for_2x1x1=48
cluster_block_rank out[0]=0 out[1]=1
```

## Where The Probe Lives

- Probe sources: `tools/cuda_probe/`
- Spark runner scripts: `scripts/cuda_probe*_spark0.sh`
