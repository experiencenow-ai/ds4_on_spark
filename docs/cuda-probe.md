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
  - `cuda_sm121_rdc_probe` (separate compilation + device link smoke test for `sm_121`)
  - `cuda_sm121_fatbin_probe` (sanity kernel built via `-gencode` with `sm_120` + `sm_121` SASS plus `compute_121` PTX)
  - `cuda_sm121_dlto_probe` (device LTO (`-dlto`) smoke test for `sm_121`)
  - `cuda_sm121_arch_report` (prints device CC + compiled `__CUDA_ARCH__`)
  - `cuda_sm120_compat_probe` (runs an `sm_120`-compiled kernel on the device; tests `sm_120`→`sm_121` compatibility)
  - `cuda_cublaslt_smoke` (tiny cuBLASLt matmul smoke test)
  - `cuda_cublaslt_fp8_smoke` (tiny cuBLASLt FP8 (E4M3) matmul smoke test)
  - `cuda_cublaslt_fp8_e5m2_smoke` (tiny cuBLASLt FP8 (E5M2) matmul smoke test)
  - `cuda_sm121_smem_optin` (shared-memory opt-in + dynamic shared memory launch)
  - `cuda_sm121_devattrs` (device attribute dump for kernel bring-up gating)
  - `cuda_sm121_fp8_conv` (`cuda_fp8.h` conversion probe for FP8 plumbing)
  - `cuda_sm121_bf16_conv` (`cuda_bf16.h` conversion probe for BF16 plumbing; CUTLASS/DeepGEMM-style gate)
  - `cuda_sm121_fp4_conv` (`cuda_fp4.h` conversion probe for FP4 (E2M1) plumbing)
  - `cuda_sm121_pipeline_memcpy_async` (`__pipeline_memcpy_async` global->shared copy probe)
  - `cuda_sm121_barrier_memcpy_async` (`cuda::barrier` + `cuda::memcpy_async` copy probe)
  - `cuda_sm121_cp_async_bulk_tx` (explicit `cp.async.bulk` global->shared copy via CCCL `cuda::device::memcpy_async_tx`)
  - `cuda_sm121_cccl_atomic_ref` (CCCL `cuda::atomic_ref` device-scope + block-scope atomics)
  - `cuda_sm121_cuda_graph_smoke` (CUDA graph capture → instantiate → launch smoke test)
  - `cuda_sm121_nvrtc_jit` (NVRTC compile-to-PTX + Driver API module load/launch for `compute_121`)
  - `cuda_sm121_nvcc_flags_probe` (nvcc `-std=c++20` + `--extended-lambda` + `--expt-relaxed-constexpr` compile/run gate for `sm_121`)
  - `cuda_sm121_nvjitlink_jit` (NVRTC compile-to-PTX + nvJitLink PTX→CUBIN + Driver API module load/launch for `sm_121`)
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
It prints `nvcc --list-gpu-arch` / `nvcc --list-gpu-code` when supported, then compiles `cuda_sm121_compile_probe.o`, `cuda_sm121_probe`, `cuda_sm121_rdc_probe`, `cuda_sm121_fatbin_probe`, `cuda_sm121_dlto_probe`, `cuda_sm121_arch_report`, `cuda_cublaslt_smoke`, `cuda_cublaslt_fp8_smoke`, `cuda_cublaslt_fp8_e5m2_smoke`, `cuda_sm121_smem_optin`, `cuda_sm121_devattrs`, `cuda_sm121_fp8_conv`, `cuda_sm121_bf16_conv`, `cuda_sm121_fp4_conv`, `cuda_sm121_pipeline_memcpy_async`, `cuda_sm121_barrier_memcpy_async`, `cuda_sm121_cp_async_bulk_tx`, `cuda_sm121_cccl_atomic_ref`, `cuda_sm121_cxx20_probe`, `cuda_sm121_nvcc_flags_probe`, `cuda_sm121_wmma_smoke`, `cuda_sm121_cluster_launch`, `cuda_sm121_nvrtc_jit`, and `cuda_sm121_nvjitlink_jit` for `sm_121`, plus `cuda_sm120_compat_probe` for `sm_120`.
It also compiles `cuda_sm121_cuda_graph_smoke` (CUDA graph capture/launch smoke test) for `sm_121`.
Finally, it attempts a standalone `nvcc -arch=sm_121` compile of a kernel using the `__cluster_dims__` attribute (`tools/cuda_probe/src/cuda_sm121_cluster_dims_attr_compile.cu`) and prints whether it compiled or the first lines of the error output.

## Current Spark0 Results (2026-05-09)

Commands run:

```bash
./scripts/cuda_probe_compile_only_spark0.sh
./scripts/cuda_probe_spark0.sh
```

Observed:

- `nvcc` is CUDA 13.0 (`V13.0.88`)
- `-arch=sm_121` compiles and links (including `-lcublasLt`)
- `nvcc -arch=sm_121` accepts the `__cluster_dims__` kernel annotation (compile-only check prints `cluster_dims_attr_compile: OK`)
- `-arch=sm_120` binaries run on GB10 (`sm_121`) successfully (probe prints `__CUDA_ARCH__=1200` on device `cc=12.1`)
- Runtime launches a tiny `sm_121` kernel successfully
- Separate compilation (`-dc`) + device link (`-dlink`) succeeds for `sm_121` (`cuda_sm121_rdc_probe` runs and validates output)
- Device LTO (`-dlto`) compile/run succeeds for `sm_121` (`cuda_sm121_dlto_probe` runs and validates output)
- cuBLASLt matmul smoke test succeeds (`max_abs_err=0`)
- cuBLASLt FP8 matmul smoke test succeeds (`max_abs_err_vs_one=0`)
- cuBLASLt FP8 (E5M2) matmul smoke probe fails to find any supported algo on Spark0 (CUDA 13.0 `V13.0.88`) even after trying `m=n=k` in `{16,64,128}`, multiple `cublasComputeType_t` values, and workspace sizes `{1MiB,16MiB}` (the Spark runner continues past this failure)
- Shared-memory opt-in probe succeeds; `MaxSharedMemoryPerBlockOptin=101376` bytes on GB10
- FP8 conversion probe succeeds (`fp8_conv ... halfraw_e4m3=0x3d00`)
- BF16 conversion probe succeeds (`cuda_bf16.h` conversions compile and run for `sm_121`)
- FP4 conversion probe succeeds (`fp4_conv ... halfraw_e2m1=0x3c00`)
- Pipeline memcpy-async probe succeeds (cp.async-style global->shared copy)
- Barrier memcpy-async probe succeeds (`cuda::barrier` + `cuda::memcpy_async`)
- Explicit `cp.async.bulk` (CCCL `memcpy_async_tx`) probe succeeds (`cuda_sm121_cp_async_bulk_tx`)
- CCCL atomic-ref probe succeeds (`cuda::atomic_ref`)
- CUDA graph smoke probe succeeds (stream capture + instantiate + launch)
- NVRTC JIT probe succeeds (`nvrtc supportedArchs` includes `121`; driver loads PTX and launches kernel)
- NVCC flags probe succeeds (`-std=c++20 --extended-lambda --expt-relaxed-constexpr`)
- nvJitLink JIT probe succeeds (nvJitLink links `compute_121` PTX to an `sm_121` CUBIN and driver loads/launches the kernel)
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
rdc_probe in=0x12345678 out=0xb791f3de expect=0xb791f3de
kernel wrote magic=0xc0d3cafe __CUDA_ARCH__=1210
dlto_probe in=0x12345678 out=0xce5cb9c3 expect=0xce5cb9c3
expect: compiled __CUDA_ARCH__=1200 for -arch=sm_120
kernel wrote magic=0xc0d3cafe __CUDA_ARCH__=1200
cuBLASLt sgemm smoke max_abs_err=0
cuBLASLt fp8 e4m3 smoke max_abs_err_vs_one=0
cuBLASLt fp8 e5m2 probe try m=128 n=128 k=128 compute_type=CUBLAS_COMPUTE_16F ws_bytes=16777216
cuBLASLt fp8 e5m2 smoke: no supported configuration found
(cuda_cublaslt_fp8_e5m2_smoke failed; continuing)
max_smem_per_block_optin_bytes=101376
smem probe wrote 0x000000a5
fp8_conv x=1.250000 e4m3=0x3a e5m2=0x3d halfraw_e4m3=0x3d00 halfraw_e5m2=0x3d00
bf16_conv x=1.250000 raw_x=0x3fa0 x_back=1.250000 y=-2.500000 raw_y=0xc020 y_back=-2.500000 v_back=(1.250000,-2.500000)
fp4_conv x=1.250000 e2m1_storage=0x02 e2m1_nibble=0x2 halfraw_e2m1=0x3c00
pipeline_memcpy_async out=11111111 22222222 33333333 44444444
barrier_memcpy_async ok first=decaf000 last=decaf01f
cluster_dims_attr_compile: OK
cuda_graph_smoke out=22222222
nvrtcVersion=13.0
nvrtc supportedArchs: 75 80 86 87 88 89 90 100 103 110 120 121
nvrtc_jit ok out=0x12345679
nvcc_flags_probe ok out=0x12345679
nvJitLinkVersion=13.0
nvjitlink_jit ok out=0x12345679
wmma_smoke C00=16.000000 C255=16.000000 max_abs_err=0.000000
cluster_launch_supported=1
max_cluster_size_portable=8
max_active_clusters_for_2x1x1=48
cluster_block_rank out[0]=0 out[1]=1
```

## Where The Probe Lives

- Probe sources: `tools/cuda_probe/`
- Spark runner scripts: `scripts/cuda_probe*_spark0.sh`
