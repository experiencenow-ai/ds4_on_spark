# CUDA Probe Implications (DeepGEMM / CUTLASS / cuBLASLt)

This file records near-term engineering implications from the CUDA probe track.

## GB10 / Spark0 Baseline

From `docs/spark0-initial-probe.md` and the probe binaries in `tools/cuda_probe/`:

- Device is `NVIDIA GB10`, compute capability `12.1` (`sm_121`)
- CUDA toolkit is installed and `nvcc` works (CUDA 13.0 on Spark0; observed `V13.0.88` on 2026-05-10)
- Spark0 snapshot (2026-05-10, via `scripts/cuda_probe_nvcc_minimal_spark0.sh`):
  - `cuda drv=13000 rt=13000` (CUDA 13.0 driver/runtime ABI)
  - `mp=48`, `l2=25165824` (24 MiB), `mem=128518373376` (~119.7 GiB), `clock_khz=2418000`, `mem_clock_khz=8533000`
  - `smem_optin=101376`, `smem_block_max=49152`, `smem_sm=102400`, `regs_block=65536`, `regs_sm=65536`, `maxblocks_sm=24`
  - If any `cudaDeviceGetAttribute` query is unavailable, the one-line schema uses `-1` for that field (to avoid silently reporting `0`).
- `tools/cuda_probe/bin/cuda_device_props_tiny` prints a single log-friendly line with driver/runtime versions plus key `device[0]` limits (CC/SMs/clocks/memory/shared-mem/L2/threads/blocks/registers + cooperative/cluster launch support)
- `scripts/cuda_probe_nvcc_minimal_spark0.sh` prints the same one-line limits schema without shipping `tools/cuda_probe/` (useful when repo transfer is blocked)
- `scripts/cuda_probe_nvcc_minimal_spark0.sh` also includes a best-effort compile-only gate for `-std=c++20 --extended-lambda --expt-relaxed-constexpr` (CUTLASS/DeepGEMM-style nvcc flags) for `sm_121` (and `compute_121` when advertised)
- `nvcc --list-gpu-arch` / `nvcc --list-gpu-code` should include `compute_121` / `sm_121` when supported by the toolkit
- For a small “kernel plumbing” bring-up gate set (no cuBLASLt), run `./scripts/cuda_probe_kernel_tiny_spark0.sh` from the Mac; it validates C++20 + template flags, inline PTX (`ldmatrix`), pipeline/bulk async copy plumbing, TMA tensor-map encode + `cp.async.bulk.tensor`, and NVRTC/nvJitLink JIT paths for `sm_121`.
- `./scripts/cuda_probe_capability_spark0.sh` accepts `WITH_KERNEL_TINY=1` to include the same kernel-plumbing gates as part of the one-command capability sweep.
- CUDA 13 developer tooling (`cuobjdump --dump-sass`, `nvdisasm`) can decode `sm_121` binaries on Spark0 (validated via `scripts/cuda_probe_disasm_spark0.sh`: 2026-05-09)
- `tools/cuda_probe/bin/cuda_sm121_arch_report` prints runtime CC + compiled `__CUDA_ARCH__` (observed `1210` for `sm_121`)
- `tools/cuda_probe/bin/cuda_sm120_compat_probe` shows that an `sm_120`-compiled kernel runs successfully on GB10 (`sm_121`) (observed `__CUDA_ARCH__=1200` on device `cc=12.1`)
- `tools/cuda_probe/bin/cuda_sm121_smem_optin` prints `cudaDevAttrMaxSharedMemoryPerBlockOptin` and validates an opt-in dynamic shared-memory launch
  - Observed on Spark0 (2026-05-08): `MaxSharedMemoryPerBlockOptin=101376` bytes
- `tools/cuda_probe/bin/cuda_sm121_devattrs` dumps key `cudaDeviceGetAttribute` values commonly used to gate kernel bring-up (shared memory, registers, L2, cooperative/cluster launch).
- `tools/cuda_probe/bin/cuda_sm121_fp8_conv` validates that CUDA 13 FP8 conversion helpers (`cuda_fp8.h`) compile and run for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_bf16_conv` validates that CUDA BF16 helpers (`cuda_bf16.h`) compile and run for `sm_121` (BF16 data plumbing gate for many CUTLASS-style kernels).
- `tools/cuda_probe/bin/cuda_sm121_fp4_conv` validates that CUDA 13 FP4 conversion helpers (`cuda_fp4.h`, E2M1) compile and run for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async` validates that CUDA pipeline primitives (`__pipeline_memcpy_async` / cp.async-style) compile and run for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_cp_async_bulk_tx` validates an explicit `cp.async.bulk` global->shared copy path via CCCL’s internal `cuda::device::memcpy_async_tx` (CUTLASS-style bulk async copy plumbing).
- `tools/cuda_probe/bin/cuda_sm121_ldmatrix_smoke` validates that inline PTX `ldmatrix.sync` loads from shared memory compile and run on `sm_121` (CUTLASS-style inline-PTX gate).
- `tools/cuda_probe/bin/cuda_sm121_tma_bulk_tensor_1d` validates a minimal TMA `cp.async.bulk.tensor.1d` load using a tensor map encoded via the driver API `cuTensorMapEncodeTiled` (CUTLASS TMA load plumbing gate).
- `tools/cuda_probe/bin/cuda_sm121_tma_bulk_tensor_2d` validates a minimal TMA `cp.async.bulk.tensor.2d` load using a tensor map encoded via the driver API `cuTensorMapEncodeTiled` (2D traversal gate used by many tile schedulers).
- `tools/cuda_probe/bin/cuda_sm121_cxx20_probe` validates that `nvcc` + the host toolchain can compile C++20 (`-std=c++20`) for `sm_121` (DeepGEMM-style build gate).
- `tools/cuda_probe/bin/cuda_sm121_nvcc_flags_probe` validates that `nvcc` accepts common template-kernel compile flags (`--extended-lambda` + `--expt-relaxed-constexpr`) with `-std=c++20` for `sm_121` (CUTLASS/DeepGEMM-style compile gate).
- `tools/cuda_probe/bin/cuda_sm121_rdc_probe` validates that `nvcc` + `nvlink` can perform separate compilation (`-dc`) + device link (`-dlink`) for `sm_121` (multi-translation-unit CUDA build gate; observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_dlto_probe` validates that `nvcc` supports device LTO (`-dlto`) for `sm_121` (toolchain gate for some CUDA build systems; observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_cccl_atomic_ref` validates CCCL atomics (`cuda::atomic_ref`) compile and run for `sm_121` (template-kernel plumbing dependency).
- `tools/cuda_probe/bin/cuda_sm121_cuda_graph_smoke` validates CUDA graph stream capture → instantiate → launch on `sm_121` (CUDAGraph-style execution gate).
- `tools/cuda_probe/bin/cuda_sm121_nvrtc_jit` validates an NVRTC “compile to PTX for `compute_121` → load via Driver API → launch kernel” path; this is a useful gate for any JIT compilation flows on GB10 (observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_nvrtc_cxx20_jit` validates NVRTC can compile C++20 (`--std=c++20`) to PTX for `compute_121` and run the resulting kernel via the Driver API (DeepGEMM-style JIT gate; observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_nvjitlink_jit` validates an NVRTC+nvJitLink “compile to PTX for `compute_121` → link to `sm_121` CUBIN → load via Driver API → launch kernel” path; this is a useful gate for JIT flows that rely on nvJitLink (observed success on Spark0: 2026-05-09).
- `tools/cuda_probe/bin/cuda_sm121_wmma_smoke` validates that WMMA (`mma.h`) tensor core matmul plumbing compiles and runs for `sm_121`.
- `tools/cuda_probe/bin/cuda_sm121_cluster_launch` validates that thread-block cluster launches (`cudaLaunchKernelExC` + `cudaLaunchAttributeClusterDimension`) and `cooperative_groups::this_cluster()` compile and run for `sm_121` (observed on Spark0: `cluster_launch_supported=1`, `max_cluster_size_portable=8`).
## cuBLASLt

Implication:

- cuBLASLt should be treated as the “works-first” baseline for GEMM paths on GB10.
- When custom kernels or template libraries fail to build for `sm_121`, cuBLASLt is the fallback for correctness gating and early performance baselines.
- The cuBLASLt smoke probes print `cublasLtGetVersion` and `cublasLtGetCudartVersion`; keep these lines in logs so failures can be correlated to the exact cuBLASLt stack.
- FP8 matmul is verified via cuBLASLt on `sm_121` for E4M3 (see `cuda_cublaslt_fp8_smoke`), which de-risks early FP8 bring-up for DeepGEMM-style paths.
- The current CUDA 13.0 (`V13.0.88`) cuBLASLt stack on Spark0 fails to find any supported algo for the E5M2 smoke probe (`cuda_cublaslt_fp8_e5m2_smoke`) even when sweeping `m=n=k` in `{16,64,128}` and workspace sizes `{1MiB,16MiB}` using the narrow-precision-recommended “TN” format (A transposed, B non-transposed) and BF16 output (observed 2026-05-10: `cublasLtGetVersion=130101`), which may matter for DeepGEMM paths that use E5M2 inputs.
- FP4 conversion helpers exist in CUDA 13 (`cuda_fp4.h`), but FP4 matmul support and packing/scale semantics are cuBLASLt-stack dependent; use `cuda_cublaslt_fp4_smoke` / `cuda_cublaslt_fp4_sweep` as the first “does FP4 GEMM exist?” gate before investing in FP4 kernels.
- Observed on Spark0 (2026-05-10 / CUDA 13.0 `V13.0.88` / `cublasLtGetVersion=130101`):
  - `cuda_cublaslt_fp4_sweep` reports `heuristic=CUBLAS_STATUS_SUCCESS got=8 rc=0` for BF16 output (`CUBLAS_COMPUTE_32F`), which suggests an FP4 matmul execution path exists in cuBLASLt on GB10.
  - `cuda_cublaslt_fp4_smoke` currently prints `max_abs_err_vs_one=1` for a naive “identity×ones” check (so treat this as “matmul runs” not “numeric validated” until we wire a correct NVFP4 pack+scale recipe).

Probe:

- `tools/cuda_probe/bin/cuda_cublaslt_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny matmul smoke test on Spark0.
- `tools/cuda_probe/bin/cuda_cublaslt_fp8_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny FP8 (E4M3) matmul smoke test on Spark0.
- `tools/cuda_probe/bin/cuda_cublaslt_fp8_e5m2_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny FP8 (E5M2) matmul smoke test on Spark0.
- `tools/cuda_probe/bin/cuda_cublaslt_fp4_smoke`: compiles for `sm_121`, links `-lcublasLt`, and runs a tiny FP4 (E2M1) matmul smoke test on Spark0 (best-effort capability probe).

## CUTLASS

Implication:

- CUTLASS is the most likely path for “bring-up on `sm_121`” when we need custom GEMMs beyond cuBLASLt.
- Any CUTLASS integration work must explicitly include `sm_121` in its arch list; do not assume `sm_100` build settings apply.
- If `sm_121` is not available in a given upstream build system yet, validate whether building for `sm_120` runs correctly on GB10 first (see `cuda_sm120_compat_probe` below).
- CUTLASS 3-style TMA loads appear viable on GB10; the `cuda_sm121_tma_bulk_tensor_1d` / `cuda_sm121_tma_bulk_tensor_2d` probes are minimal “tensor map encode + `cp.async.bulk.tensor`” gates that should fail fast if TMA plumbing is missing or broken.
- The “kernel plumbing” probe set (`./scripts/cuda_probe_kernel_tiny_spark0.sh`) already covers many CUTLASS prerequisites on GB10: C++20 compilation, common nvcc template flags, inline PTX (`ldmatrix.sync`), async copy plumbing (pipeline + CCCL `cp.async.bulk`), and TMA tensor-map encode + `cp.async.bulk.tensor`.
- When repo transfer is blocked (or you want a faster gate), `./scripts/cuda_probe_nvcc_minimal_spark0.sh` includes a compile-only `-std=c++20 --extended-lambda --expt-relaxed-constexpr` check for `sm_121` to catch “toolchain can’t compile CUTLASS-style code” failures early.
- A real CUTLASS bring-up still needs a minimal CUTLASS compile+run probe, because CUTLASS may hard-gate unknown arch tags (`sm_121`) or require a small arch mapping patch even when the toolchain is otherwise healthy.

Next probe step:

- Verify a minimal CUTLASS example can compile for `sm_121` and run on Spark0 before committing to a larger CUTLASS-based kernel path.
- Run `tools/cuda_probe/bin/cuda_sm120_compat_probe` on Spark0 to establish whether `sm_120` SASS is a viable short-term compatibility target for GB10.
- Confirm the required shared-memory footprint fits within `cudaDevAttrMaxSharedMemoryPerBlockOptin` for any CUTLASS kernels we plan to bring up.
- Confirm that pipeline primitives (cp.async-style global->shared copies) work on GB10; see `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async`.
- Confirm that bulk async copy plumbing compiles and runs on GB10; see `tools/cuda_probe/bin/cuda_sm121_cp_async_bulk_tx` (explicit `cp.async.bulk` path used by CCCL/CUTLASS-style code).
- Confirm that inline PTX mainloop plumbing is viable on GB10; see `tools/cuda_probe/bin/cuda_sm121_ldmatrix_smoke` (inline PTX `ldmatrix.sync` gate).
- Confirm that tensor core matmul plumbing works on GB10; see `tools/cuda_probe/bin/cuda_sm121_wmma_smoke`.
- Confirm that BF16 conversion/data plumbing works on GB10; see `tools/cuda_probe/bin/cuda_sm121_bf16_conv`.
- Confirm that cluster launches and cluster intrinsics work on GB10; see `tools/cuda_probe/bin/cuda_sm121_cluster_launch`.
- If using cluster annotations (`__cluster_dims__`) in any CUTLASS-style code, verify whether `nvcc -arch=sm_121` accepts it on Spark0; `./scripts/cuda_probe_compile_only_spark0.sh`, `./scripts/cuda_probe_compile_only_tiny_spark0.sh`, and `./scripts/cuda_probe_nvcc_minimal_spark0.sh` print a `cluster_dims_attr_compile` result (observed `OK` on 2026-05-09 with CUDA 13.0 `V13.0.88`).
- Note: this repo’s pinned DeepGEMM upstream uses a CUTLASS submodule; we intentionally do not auto-init submodules in the probe loop (see `docs/upstream-deepgemm.md`), so a CUTLASS compile/run probe requires an explicit submodule init (extra downloads).

## Build Portability Notes (CUDA 13)

Implication:

- `-arch=native` is convenient for single-host bring-up, but `nvcc` generates SASS for the visible GPU(s) and (per CUDA 13 `nvcc` docs) does not embed PTX; this is not ideal for “ship one binary and run anywhere”.
- `scripts/cuda_probe_compile_only_tiny_spark0.sh` and `scripts/cuda_probe_nvcc_minimal_spark0.sh` both include best-effort `cuobjdump --dump-ptx` checks to make the “PTX present vs missing” behavior observable on Spark0.
- When PTX is present, those scripts also print the first PTX `.target` line (`ptx_target_*`) so logs capture the embedded PTX arch explicitly.
- Those same scripts also attempt best-effort compile-only `-gencode` builds for `arch=compute_121,code=sm_121` and `arch=compute_121,code=compute_121` (when `compute_121` is advertised) to validate multi-target build plumbing on the installed `nvcc`.
- For artifacts expected to run across multiple GPU variants, prefer explicit `-gencode` with both SASS and PTX (for example: `-gencode arch=compute_121,code=sm_121 -gencode arch=compute_121,code=compute_121`, or `-gencode arch=compute_121,code=[sm_121,compute_121]`) and add additional `sm_*` entries as needed for your fleet.
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
- Confirm that `cuda_bf16.h` conversion/data helpers compile and run on GB10 (DeepGEMM-like kernels often use BF16 intermediates); see `tools/cuda_probe/bin/cuda_sm121_bf16_conv`.
- Confirm that `cuda_fp4.h` conversion helpers compile and run on GB10 if FP4 paths are needed; see `tools/cuda_probe/bin/cuda_sm121_fp4_conv`.
- Confirm that pipeline primitives (cp.async-style mainloop plumbing) compile and run on GB10; see `tools/cuda_probe/bin/cuda_sm121_pipeline_memcpy_async`.
- If DeepGEMM depends on large dynamic shared memory, use `cuda_sm121_smem_optin` output as the initial feasibility gate before deeper porting work.
- If DeepGEMM is blocked on missing submodules, use `cuda_sm121_devattrs` to record the baseline device limits and features while deciding whether to pull CUTLASS into the tree.
