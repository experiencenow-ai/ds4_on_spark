# CUDA Probe Tools

Tiny CUDA compile/run probes for DGX Spark (GB10) acceptance work.

## Build (on Spark0)

```bash
cd tools/cuda_probe
make
```

Expected outputs:

- `tools/cuda_probe/bin/cuda_device_props`: print basic device/runtime info.
- `tools/cuda_probe/bin/cuda_device_props_tiny`: one-line device/runtime summary (fast log-friendly).
- `tools/cuda_probe/bin/cuda_sm121_compile_probe.o`: compile-only object that requires `-arch=sm_121` support (no runtime needed).
- `tools/cuda_probe/bin/cuda_sm121_probe`: compile/run sanity kernel for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_rdc_probe`: compile/run separate-compilation (`-rdc=true`) device-link smoke test for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_fatbin_probe`: compile/run sanity kernel built with explicit `-gencode` (includes `sm_120` + `sm_121` SASS and `compute_121` PTX).
- `tools/cuda_probe/bin/cuda_sm121_dlto_probe`: compile/run device LTO (`-dlto`) smoke test for `sm_121` (toolchain gate for some CUDA build systems).
- `tools/cuda_probe/bin/cuda_sm121_arch_report`: print runtime CC + compiled `__CUDA_ARCH__`.
- `tools/cuda_probe/bin/cuda_sm120_compat_probe`: compile for `sm_120` and run on the device; tests `sm_120`→`sm_121` compatibility.
- `tools/cuda_probe/bin/cuda_cublaslt_smoke`: link/run tiny cuBLASLt matmul for `sm_121`.
- `tools/cuda_probe/bin/cuda_cublaslt_fp8_smoke`: link/run tiny cuBLASLt FP8 (E4M3) matmul for `sm_121`.
- `tools/cuda_probe/bin/cuda_cublaslt_fp8_e5m2_smoke`: link/run tiny cuBLASLt FP8 (E5M2) matmul for `sm_121` (tries multiple compute types; prints diagnostics).
- `tools/cuda_probe/bin/cuda_sm121_smem_optin`: print `MaxSharedMemoryPerBlockOptin` and run a dynamic shared-memory launch.
- `tools/cuda_probe/bin/cuda_sm121_devattrs`: dump CUTLASS/DeepGEMM-relevant `cudaDeviceGetAttribute` values.
- `tools/cuda_probe/bin/cuda_sm121_fp8_conv`: compile/run FP8 conversion plumbing via `cuda_fp8.h`.
- `tools/cuda_probe/bin/cuda_sm121_bf16_conv`: compile/run BF16 conversion plumbing via `cuda_bf16.h`.
- `tools/cuda_probe/bin/cuda_sm121_fp4_conv`: compile/run FP4 (E2M1) conversion plumbing via `cuda_fp4.h`.
- `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async`: compile/run a `__pipeline_memcpy_async` (cp.async-style) copy from global->shared.
- `tools/cuda_probe/bin/cuda_sm121_barrier_memcpy_async`: compile/run `cuda::memcpy_async(..., barrier)` using CCCL’s `<cuda/barrier>` API.
- `tools/cuda_probe/bin/cuda_sm121_cp_async_bulk_tx`: compile/run an explicit `cp.async.bulk` global->shared copy path via CCCL’s internal `cuda::device::memcpy_async_tx` (CUTLASS-style bulk async copy plumbing).
- `tools/cuda_probe/bin/cuda_sm121_cccl_atomic_ref`: compile/run CCCL `cuda::atomic_ref` (device-scope + block-scope) atomics on `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_cuda_graph_smoke`: compile/run CUDA graph capture → instantiate → launch smoke test on `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_nvrtc_jit`: compile PTX via NVRTC (`--gpu-architecture=compute_121`), load via CUDA Driver API, and launch a tiny kernel.
- `tools/cuda_probe/bin/cuda_sm121_nvcc_flags_probe`: compile/run a device-lambda kernel using `--extended-lambda` + `--expt-relaxed-constexpr` with `-std=c++20` for `sm_121` (CUTLASS/DeepGEMM-style compile flags gate).
- `tools/cuda_probe/bin/cuda_sm121_nvjitlink_jit`: compile PTX via NVRTC, link to CUBIN via nvJitLink (`-arch=sm_121`), then load via CUDA Driver API and launch a tiny kernel.
- `tools/cuda_probe/bin/cuda_sm121_cxx20_probe`: compile/run `-std=c++20` toolchain smoke test for `sm_121` (DeepGEMM-style build gate).
- `tools/cuda_probe/bin/cuda_sm121_wmma_smoke`: compile/run a tiny WMMA (`mma.h`) matmul smoke test on `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_cluster_launch`: compile/run a thread-block cluster launch (`cudaLaunchKernelExC` + `cudaLaunchAttributeClusterDimension`) and validate `cooperative_groups::this_cluster().block_rank()`.

## Run

```bash
./tools/cuda_probe/bin/cuda_device_props
./tools/cuda_probe/bin/cuda_device_props_tiny
./tools/cuda_probe/bin/cuda_sm121_probe
./tools/cuda_probe/bin/cuda_sm121_rdc_probe
./tools/cuda_probe/bin/cuda_sm121_fatbin_probe
./tools/cuda_probe/bin/cuda_sm121_dlto_probe
./tools/cuda_probe/bin/cuda_sm121_arch_report
./tools/cuda_probe/bin/cuda_sm120_compat_probe
./tools/cuda_probe/bin/cuda_cublaslt_smoke
./tools/cuda_probe/bin/cuda_cublaslt_fp8_smoke
./tools/cuda_probe/bin/cuda_cublaslt_fp8_e5m2_smoke
./tools/cuda_probe/bin/cuda_sm121_smem_optin
./tools/cuda_probe/bin/cuda_sm121_devattrs
./tools/cuda_probe/bin/cuda_sm121_fp8_conv
./tools/cuda_probe/bin/cuda_sm121_bf16_conv
./tools/cuda_probe/bin/cuda_sm121_fp4_conv
./tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async
./tools/cuda_probe/bin/cuda_sm121_barrier_memcpy_async
./tools/cuda_probe/bin/cuda_sm121_cp_async_bulk_tx
./tools/cuda_probe/bin/cuda_sm121_cccl_atomic_ref
./tools/cuda_probe/bin/cuda_sm121_cuda_graph_smoke
./tools/cuda_probe/bin/cuda_sm121_nvrtc_jit
./tools/cuda_probe/bin/cuda_sm121_nvcc_flags_probe
./tools/cuda_probe/bin/cuda_sm121_nvjitlink_jit
./tools/cuda_probe/bin/cuda_sm121_cxx20_probe
./tools/cuda_probe/bin/cuda_sm121_wmma_smoke
./tools/cuda_probe/bin/cuda_sm121_cluster_launch
```

## Notes

- `cuda_sm121_probe` compiles for `-arch=sm_121` and should fail fast if `nvcc`
  or the installed toolkit does not recognize `sm_121`.
- `cuda_sm121_rdc_probe` is a compile/run check that `nvcc` can do separate compilation (`-dc`) plus device link (`-dlink`) for `sm_121`; this is a common requirement for multi-translation-unit CUDA codebases and build systems.
- `cuda_sm121_fatbin_probe` compiles for multiple targets via `-gencode` so the
  output contains both `sm_120` + `sm_121` SASS, plus PTX for `compute_121`
  (useful when you need “one binary” portability and/or want a short-term
  fallback while upstream build systems catch up to `sm_121`).
- `cuda_sm121_dlto_probe` is a compile/run check that `nvcc` supports device LTO (`-dlto`) for `sm_121`; treat failures as a blocker for CUDA build systems that enable device LTO by default.
- `cuda_sm121_compile_probe.o` is a compile-only smoke check; it does not link
  against `cudart` and is useful when you only need to confirm that `nvcc`
  recognizes `sm_121`.
- `cuda_cublaslt_smoke` is a minimal “link + run” check for `-lcublasLt` on
  `sm_121`.
- `cuda_cublaslt_fp8_smoke` is a minimal “link + run” check for FP8 E4M3 matmul
  via cuBLASLt on `sm_121`.
- `cuda_cublaslt_fp8_e5m2_smoke` is a minimal “link + run” check for FP8 E5M2
  matmul via cuBLASLt on `sm_121` (tries multiple compute types; observed on Spark0 / CUDA 13.0 `V13.0.88`: returns `CUBLAS_STATUS_NOT_SUPPORTED` during heuristic selection).
- `cuda_sm120_compat_probe` is a minimal “run an `sm_120`-compiled kernel on the device” check; if it succeeds on Spark0, it suggests `sm_120` SASS is a viable short-term compatibility target for GB10 (`sm_121`) (observed success on 2026-05-09).
- `cuda_sm121_smem_optin` is an opt-in shared-memory sanity check used by
  CUTLASS-style kernels that rely on `cudaFuncAttributeMaxDynamicSharedMemorySize`.
- `cuda_sm121_devattrs` records device limits and runtime feature gates that commonly gate
  CUTLASS / custom GEMM kernel bring-up.
- `cuda_sm121_fp8_conv` is a compile/run check for CUDA’s FP8 conversion helpers.
- `cuda_sm121_bf16_conv` is a compile/run check for CUDA’s BF16 conversion helpers.
- `cuda_sm121_fp4_conv` is a compile/run check for CUDA’s FP4 conversion helpers (`cuda_fp4.h`, E2M1).
- `cuda_sm121_pipeline_memcpy_async` is a compile/run check for CUDA pipeline primitives (`cuda_pipeline_primitives.h`) used by cp.async-style kernels.
- `cuda_sm121_barrier_memcpy_async` is a compile/run check for CCCL’s higher-level `cuda::barrier` + `cuda::memcpy_async` API (commonly used by templated kernels).
- `cuda_sm121_cp_async_bulk_tx` is a compile/run check for CCCL’s internal `cuda::device::memcpy_async_tx` helper, which lowers to an explicit `cp.async.bulk` global->shared copy path on SM90+.
- `cuda_sm121_cccl_atomic_ref` is a compile/run check for CCCL atomics (`cuda::atomic_ref`), which many template kernels use for counters, epilogues, and synchronization-side channels.
- `cuda_sm121_cuda_graph_smoke` is a compile/run check that CUDA graph stream capture, instantiation, and launch work correctly for `sm_121`.
- `cuda_sm121_nvrtc_jit` is a compile/run check for NVRTC + the driver PTX loader; it validates `--gpu-architecture=compute_121` and a minimal “compile PTX → load module → launch kernel” path used by JIT compilation flows.
- `cuda_sm121_nvcc_flags_probe` is a compile/run check that `nvcc` accepts and successfully uses `--extended-lambda` + `--expt-relaxed-constexpr` with `-std=c++20` for `sm_121`; this is a common compile-flags gate for CUTLASS/DeepGEMM-style codebases.
- `cuda_sm121_nvjitlink_jit` extends the NVRTC JIT probe by linking PTX to a device CUBIN via nvJitLink (`-arch=sm_121`) before loading via the Driver API; this is a useful gate for toolchains that rely on nvJitLink in their JIT flow.
- `cuda_sm121_cxx20_probe` is a compile/run check that CUDA `nvcc` + the host toolchain can build C++20 code for `sm_121`.
- `cuda_sm121_wmma_smoke` is a compile/run check for WMMA (`mma.h`) tensor core matmul plumbing, as a tiny proxy for CUTLASS-style kernels.
- `cuda_sm121_cluster_launch` is a compile/run check for thread-block cluster launches and cluster group intrinsics; cluster launches are used by newer CUTLASS kernels and other advanced scheduling patterns.
- `__cluster_dims__` compile note: `./scripts/cuda_probe_compile_only_spark0.sh` also attempts a standalone compile of `tools/cuda_probe/src/cuda_sm121_cluster_dims_attr_compile.cu` (kernel annotated with `__cluster_dims__(2,1,1)`) and prints whether it compiled or the first lines of the error; this is useful because some toolkits reject the annotation for `sm_121` even when runtime cluster launch via `cudaLaunchKernelExC` works.
- These probes intentionally keep dependencies tiny and print errors verbatim so
  failures can be pasted into an issue/PR.
