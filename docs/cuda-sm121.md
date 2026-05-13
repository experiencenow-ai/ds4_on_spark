# CUDA 13 + `sm_121` Notes

Spark0 reports compute capability `12.1`, which corresponds to `sm_121` in `nvcc`.

## Build Flags

For reproducible builds targeting GB10:

- Prefer `-arch=sm_121`, or
- Use explicit `-gencode` (for example: `-gencode arch=compute_121,code=sm_121` for SASS, and add `-gencode arch=compute_121,code=compute_121` when you want embedded PTX for JIT portability).
- `nvcc` also supports a bracket-list syntax for multi-code builds (for example: `-gencode arch=compute_121,code=[sm_121,compute_121]`). `scripts/cuda_probe_compile_only_tiny_spark0.sh` includes a best-effort compile-only probe for this form when `compute_121` is advertised.
- The probe `tools/cuda_probe/bin/cuda_sm121_fatbin_probe` is built via explicit `-gencode` and includes both `sm_120` + `sm_121` SASS plus `compute_121` PTX as a “portable fatbin” reference.

For convenience on single-GPU bring-up:

- `-arch=native` will compile for the visible GPU(s) detected by `nvcc` at build time.
  - `scripts/cuda_probe_compile_only_tiny_spark0.sh` performs a best-effort `-fatbin` + `cuobjdump --dump-ptx` check for `-arch=native` and reports whether PTX is embedded (expected missing; treat as a portability signal, not a functional failure).
  - When PTX is present in any of these checks, the scripts print the first PTX `.target` line (`ptx_target_*`) to make the embedded PTX arch explicit in logs.

The probe `tools/cuda_probe/bin/cuda_sm121_arch_list_report` prints `__CUDA_ARCH_LIST__` (and CUDA 13 feature-set macros when present) at runtime for a normal `-arch=sm_121` build, which is handy when diagnosing “what arch list did `nvcc` think we built?” issues.

The probe `tools/cuda_probe/bin/cuda_sm121_compile_report_tiny` prints a single line with NVCC/CUDART macro versions plus device CC and `__CUDA_ARCH__` / `__CUDA_ARCH_LIST__` (useful for log capture in automation runs).

### CUDA 13 NVCC Linkage / Visibility Defaults

CUDA 13 changes `nvcc` defaults that can matter for CUTLASS/DeepGEMM-style builds:

- `-static-global-template-stub=true` (default in CUDA 13) can break “explicitly instantiate a `__global__` template in TU A, launch it from TU B” in whole-program compilation mode (`-rdc=false`). Fix options include `-rdc=true` or `-static-global-template-stub=false`. `scripts/cuda_probe_nvcc_minimal_spark0.sh` prints `template_stub_default` / `template_stub_stubfalse` / `template_stub_rdc` as a concrete Spark0 check.
- `-device-entity-has-hidden-visibility=true` (default in CUDA 13) forces hidden ELF visibility for `__global__` functions and device variables when building shared libraries (can cause link errors across `.so` boundaries unless you opt out and ensure a single shared CUDART).

Observed on Spark0 (2026-05-12 / CUDA 13.0 `V13.0.88`): `template_stub_default` fails to link (warning `#20280-D` + undefined reference), while `template_stub_stubfalse` (`-static-global-template-stub=false`) and `template_stub_rdc` (`-rdc=true`) both build and run successfully.

### `sm_121a` / `sm_121f` Variant Targets (Toolchain Probe)

CUDA 13 toolchains may also advertise variant targets like `sm_121a` and `sm_121f` in `nvcc --list-gpu-code`.

`scripts/cuda_probe_compile_only_tiny_spark0.sh` always attempts best-effort compile-only builds for `sm_121a` and `sm_121f`, and reports whether each target was advertised by `nvcc --list-gpu-code` (`advertised=yes/no/unknown`) plus `variant_sm_121a` / `variant_sm_121f` as `OK` or `FAILED` (informational; the script still treats missing `sm_121` as the hard failure). It also runs the same best-effort probe via the long-form flag `nvcc --gpu-architecture=...` and prints `variant_gpuarch_sm_121a` / `variant_gpuarch_sm_121f`.

Observed on Spark0 (2026-05-12 / CUDA 13.0 `V13.0.88`): `nvcc --list-gpu-code` includes `sm_121` but does not list `sm_121a` or `sm_121f`; best-effort compile-only `-arch=sm_121a` and `-arch=sm_121f` both succeed, best-effort compile-only `--gpu-architecture=sm_121a` / `sm_121f` also succeeds, best-effort build+run via `scripts/cuda_probe_nvcc_minimal_spark0.sh` also succeeds for both, and best-effort build+run of `cuda_sm121_fatbin_probe` via `scripts/cuda_probe_kernel_tiny_spark0.sh` reports `__CUDA_ARCH_LIST__=1210` with kernel `__CUDA_ARCH__=1210` for both `sm_121a` and `sm_121f` (treat as “accepted aliases”, not a distinct target).

Observed on Spark0 (2026-05-12 / CUDA 13.0 `V13.0.88`): `scripts/cuda_probe_tiny_spark0.sh` best-effort builds and runs `cuda_sm121a_arch_list_report` / `cuda_sm121f_arch_list_report`; both print `__CUDA_ARCH_LIST__=1210` and still report `__CUDA_ARCH_SPECIFIC__=(missing)` / `__CUDA_ARCH_FAMILY_SPECIFIC__=(missing)` (treat as “aliases accepted, feature-set macros not surfaced”).

Observed on Spark0 (2026-05-12 / CUDA 13.0 `V13.0.88`): `scripts/cuda_probe_nvcc_minimal_spark0.sh` reports that `nvcc -ptx -arch=sm_121a` / `sm_121f` emits PTX whose `.target` line is `.target sm_121a` / `.target sm_121f`, but `cuobjdump --dump-ptx` on the resulting `-arch=sm_121a` / `sm_121f` fatbins reports embedded PTX whose first `.target` line is still `.target sm_121` (and kernels still report `__CUDA_ARCH__=1210`) (treat as accepted aliases, not a distinct target for portability planning).

### `compute_121` Virtual-Arch Compile (Toolchain Probe)

When `nvcc --list-gpu-arch` is supported and includes `compute_121`, `scripts/cuda_probe_compile_only_tiny_spark0.sh` also does a best-effort compile with `-arch=compute_121` (virtual-arch / PTX-target probe) and prints `arch_compute_121` as `OK` or `FAILED` (informational; missing `sm_121` remains the hard failure).

For an end-to-end “PTX → driver/runtime JIT → run” gate, `scripts/cuda_probe_nvcc_minimal_spark0.sh` also builds and runs the same minimal probe via `-arch=compute_121` when `compute_121` is advertised.

Observed on Spark0 (2026-05-12 / CUDA 13.0 `V13.0.88`): `nvcc -ptx -arch=compute_121` emits PTX whose first `.target` line is still `.target sm_121` (and `compute_121a` / `compute_121f` emit `.target sm_121a` / `.target sm_121f`). Treat this as a “virtual-arch accepted, but PTX `.target` uses `sm_*` spelling” detail when writing log parsers and portability checks.

### `compute_121a` / `compute_121f` Feature-Set Macro Probe (Toolchain Probe)

CUDA 13 adds architecture-specific (`a`) and family-specific (`f`) feature-set targets, which are intended to define `__CUDA_ARCH_SPECIFIC__` / `__CUDA_ARCH_FAMILY_SPECIFIC__` for device code.

`scripts/cuda_probe_compile_only_tiny_spark0.sh` includes best-effort compile-only probes:

- `featureset_compute_121a` (expects `__CUDA_ARCH__==1210` and both `__CUDA_ARCH_SPECIFIC__` and `__CUDA_ARCH_FAMILY_SPECIFIC__` defined)
- `featureset_compute_121f` (expects `__CUDA_ARCH__==1210` and only `__CUDA_ARCH_FAMILY_SPECIFIC__` defined)

These probes are informational; the hard failure for GB10 targeting remains “missing `sm_121` support”.

Observed on Spark0 (2026-05-13 / CUDA 13.0 `V13.0.88`): the toolchain accepts `-arch=compute_121a` / `-arch=compute_121f`; the feature-set macro compile probes report `compute_121a`: `__CUDA_ARCH_SPECIFIC__=1210` and `__CUDA_ARCH_FAMILY_SPECIFIC__=1210`, while `compute_121f` reports `__CUDA_ARCH_SPECIFIC__=(missing)` and `__CUDA_ARCH_FAMILY_SPECIFIC__=1210` (treat `*f` as “family-specific only” in macro gating).

### NVCC `__CUDA_ARCH_LIST__` (Toolchain Introspection)

NVCC defines `__CUDA_ARCH_LIST__` as a comma-separated list of virtual architectures compiled in the current invocation.

Both `scripts/cuda_probe_nvcc_minimal_spark0.sh` and `scripts/cuda_probe_compile_only_tiny_spark0.sh` print a best-effort `__CUDA_ARCH_LIST__` snapshot for `-arch=sm_121`, `-arch=sm_121a`, and `-arch=sm_121f` (tags: `arch_list_sm_121`, `arch_list_sm_121a`, `arch_list_sm_121f`). Use this when you need to confirm what “extra virtual arches” NVCC adds when compiling `sm_121a` / `sm_121f`.

Observed on Spark0 (2026-05-12 / CUDA 13.0 `V13.0.88`): all three probes report `__CUDA_ARCH_LIST__=1210` (so the `a`/`f` suffix does not show up in the macro list).

### NVCC `-arch=sm_121` Shorthand PTX Embed (Best-Effort)

For simple builds, `nvcc` accepts a real-arch `-arch=sm_121` shorthand and can embed both `sm_121` SASS and a PTX fallback for JIT.

`scripts/cuda_probe_compile_only_tiny_spark0.sh` performs a best-effort check by emitting a `-fatbin` with `-arch=sm_121` and using `cuobjdump --dump-ptx` to confirm an embedded PTX section exists.
When PTX is present, it also prints the first PTX `.target` line (`ptx_target_sm_121`) for quick arch verification.

## CUDA 13 `cudaDeviceProp` Layout Change

On Spark0’s CUDA 13.0 headers, `struct cudaDeviceProp` no longer includes fields like `clockRate`.

If you need clocks or other dynamic properties, use:

- `cudaDeviceGetAttribute(..., cudaDevAttrClockRate, ...)`
- `cudaDeviceGetAttribute(..., cudaDevAttrMemoryClockRate, ...)`

The `tools/cuda_probe/bin/cuda_device_props` probe is written to follow this pattern.

The no-repo-transfer probe script `scripts/cuda_probe_nvcc_minimal_spark0.sh` also uses `cudaDeviceGetAttribute` (not `cudaDeviceProp` fields) to print clocks and other key limits in a log-friendly one-line format.

## Verifying `nvcc` Arch Mapping

`tools/cuda_probe/bin/cuda_sm121_arch_report` prints both:

- Runtime CC from `cudaGetDeviceProperties` (e.g. `12.1`)
- The compiled device macro `__CUDA_ARCH__` from a `-arch=sm_121` build (expected `1210`)

If your toolkit supports it, `nvcc --list-gpu-arch` and `nvcc --list-gpu-code` should include `compute_121` / `sm_121`.

The Spark0 tiny scripts treat missing `compute_121` / `sm_121` entries as errors when those `nvcc --list-*` commands are supported.

The Spark0 tiny smoke script (`scripts/cuda_probe_tiny_spark0.sh`) builds and runs `cuda_sm121_arch_report` plus the `cuda_sm121_rdc_probe` / `cuda_sm121_dlto_probe` link gates as part of the fast-path validation.

When `nvcc --list-gpu-arch` is supported and advertises `compute_121`, that same fast-path script also runs an explicit compile-only `-gencode arch=compute_121,code=[sm_121,compute_121]` gate so “fatbin PTX+SASS packaging” regressions show up quickly.

For a compile-only toolchain gate (no link, no run), `make bin/cuda_sm121_compile_probe.o` compiles `tools/cuda_probe/src/cuda_sm121_compile_probe.cu` with `-arch=sm_121` and fails the build if the device pass does not see `__CUDA_ARCH__=1210`.

Some build systems use long-form `nvcc` flags instead of `-arch=...`:

- `make bin/cuda_sm121_gpuarch_compile_probe.o` is the same source compiled via `nvcc --gpu-architecture=sm_121` (compatibility gate).
- `make bin/cuda_sm121_gpuarch_code_compile_probe.o` is the same source compiled via `nvcc --gpu-architecture=compute_121 --gpu-code=sm_121` (compatibility gate for split arch/code builds).

For an end-to-end link/run smoke check using the long-form `--gpu-architecture=sm_121` spelling, `scripts/cuda_probe_nvcc_minimal_spark0.sh` also compiles and runs the minimal probe via `nvcc --gpu-architecture=sm_121`.

For a compile-only “C++20 + flags” toolchain gate (no link, no run), `make bin/cuda_sm121_cxx20_flags_compile_probe.o` compiles `tools/cuda_probe/src/cuda_sm121_cxx20_flags_compile_probe.cu` with `-std=c++20 --extended-lambda --expt-relaxed-constexpr -arch=sm_121` and fails the build if the device pass does not see `__CUDA_ARCH__=1210` (and if `nvcc` does not define the expected flag macros). `make bin/cuda_sm121_cxx20_flags_gpuarch_compile_probe.o` is the same source compiled via `nvcc --gpu-architecture=sm_121` for build-system compatibility.

When diagnosing toolchain issues, `scripts/cuda_probe_nvcc_minimal_spark0.sh` also prints `ptxas --version` and `nvlink --version` (when present) and emits a small `-Xptxas=-v` compile-only snippet for `-arch=sm_121` so you can confirm which assembler/linker is actually being used on Spark0.

## Separate Compilation / Device Link (`-rdc=true`)

Some CUDA codebases (and some build systems) rely on separate compilation and device linking (`nvlink`), especially when device functions span translation units.

The probe `tools/cuda_probe/bin/cuda_sm121_rdc_probe` is a tiny multi-translation-unit smoke test that builds via:

- `nvcc -dc` (relocatable device code objects)
- `nvcc -dlink` (device link step)
- final host link

If this probe fails to link for `sm_121`, treat it as a toolchain/blocker for any multi-file CUDA components (even if single-file `-arch=sm_121` probes compile and run).

Observed on Spark0 (2026-05-12): `rdc_probe in=0x12345678 out=0xb791f3de expect=0xb791f3de`.

## Device LTO (`-dlto`)

Some CUDA build systems enable device link-time optimization (LTO) to reduce register pressure and improve kernel inlining across translation units.

The probe `tools/cuda_probe/bin/cuda_sm121_dlto_probe` is a tiny compile/run gate that builds with `nvcc -arch=sm_121 -dlto` and validates a one-word kernel writeback.

Observed on Spark0 (2026-05-12): `dlto_probe in=0x12345678 out=0xce5cb9c3 expect=0xce5cb9c3`.

## NVRTC JIT Compile For `compute_121`

Some stacks compile CUDA device code at runtime (NVRTC) and then load PTX via the CUDA Driver API.

The probe `tools/cuda_probe/bin/cuda_sm121_nvrtc_jit`:

- Calls `nvrtcGetSupportedArchs` and prints the supported virtual architectures (e.g. `80`, `90`, `100`, …).
- Compiles a tiny kernel with `--gpu-architecture=compute_121` to PTX via NVRTC.
- Loads the PTX with `cuModuleLoadDataEx` and launches the kernel, validating a minimal “NVRTC → PTX → Driver load → launch” path.

If this probe fails with `NVRTC_ERROR_INVALID_OPTION` or `NVRTC_ERROR_COMPILATION`, treat it as “NVRTC cannot target `compute_121` on this host/toolkit” even if `nvcc -arch=sm_121` works.

Observed on Spark0 (2026-05-12): `nvrtc supportedArchs` includes `121`, and the probe prints `nvrtc_jit ok`.

### NVRTC `--std=c++20` Gate (DeepGEMM-style JIT)

DeepGEMM-style stacks compile CUDA code at runtime and often require C++20 in the NVRTC compile step.

The probe `tools/cuda_probe/bin/cuda_sm121_nvrtc_cxx20_jit` is a tiny compile/run check that:

- Compiles a tiny kernel with `--std=c++20 --gpu-architecture=compute_121` via NVRTC.
- Loads the PTX via the CUDA Driver API and launches the kernel.

If this probe fails, treat it as “NVRTC cannot compile C++20 for `compute_121` on this toolkit”, even if `nvcc -arch=sm_121 -std=c++20` works.

Observed on Spark0 (2026-05-12): probe prints `nvrtc_cxx20_jit ok out=0x1234567a`.

## nvcc Extended Lambda + Relaxed Constexpr Gate

Many CUTLASS/DeepGEMM-style codebases rely on `nvcc` accepting and correctly compiling with flags like:

- `--extended-lambda`
- `--expt-relaxed-constexpr`

The probe `tools/cuda_probe/bin/cuda_sm121_nvcc_flags_probe` is a tiny compile/run check that:

- builds for `-arch=sm_121` with `-std=c++20`
- uses a device lambda in a kernel (exercises `--extended-lambda`)
- runs a one-word sanity writeback (`0x12345679`)

Observed on Spark0 (2026-05-12): probe prints `nvcc_flags_probe ok out=0x12345679`.

## nvJitLink JIT Link For `sm_121` (PTX → CUBIN)

Some JIT pipelines compile CUDA source to PTX and then use nvJitLink to link PTX into an `sm_121` CUBIN before loading via the CUDA Driver API.

The probe `tools/cuda_probe/bin/cuda_sm121_nvjitlink_jit`:

- Compiles a tiny kernel to PTX via NVRTC (`--gpu-architecture=compute_121`)
- Uses nvJitLink (`-arch=sm_121`) to link PTX into a device CUBIN
- Loads the CUBIN with `cuModuleLoadDataEx` and launches the kernel, validating a minimal “NVRTC → PTX → nvJitLink → CUBIN → Driver load → launch” path

If this probe fails with `NVJITLINK_ERROR_MISSING_ARCH` or linker errors, treat it as “nvJitLink cannot target `sm_121` on this host/toolkit” even if `nvcc -arch=sm_121` works.

Observed on Spark0 (2026-05-12): probe prints `nvJitLinkVersion=13.0` and `nvjitlink_jit ok`.

## CUDA Graph Stream Capture / Launch

Many inference stacks (and some kernel libraries) use CUDA Graph stream capture to reduce kernel launch overhead and improve scheduling determinism.

The probe `tools/cuda_probe/bin/cuda_sm121_cuda_graph_smoke` is a tiny compile/run check that:

- creates a non-default stream
- begins stream capture (`cudaStreamBeginCapture`)
- captures two tiny kernel launches that write a u32 value
- ends capture to a `cudaGraph_t`, instantiates it (`cudaGraphInstantiateWithFlags`), and launches it (`cudaGraphLaunch`)
- validates that the final writeback matches the expected value

Observed on Spark0 (2026-05-12): probe prints `cuda_graph_smoke out=22222222`.

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

## BF16 Header + Conversion Plumbing

Many CUTLASS/DeepGEMM-style kernels use BF16 intermediates.

The probe `tools/cuda_probe/bin/cuda_sm121_bf16_conv` is a tiny compile/run check that:

- includes `cuda_bf16.h`
- converts floats to `__nv_bfloat16_raw` and back
- prints the raw BF16 bits and float round-trips

## FP4 Header + Conversion Plumbing

Some DeepGEMM-style paths may use FP4 (E2M1). CUDA 13 ships FP4 helpers under `cuda_fp4.h`.

The probe `tools/cuda_probe/bin/cuda_sm121_fp4_conv` is a tiny compile/run check that:

- includes `cuda_fp4.h`
- converts a `float` to FP4 storage (`e2m1`)
- converts back to `__half_raw` and prints the raw bits

## cuBLASLt FP4 (E2M1) Smoke

The probe `tools/cuda_probe/bin/cuda_cublaslt_fp4_smoke` is a best-effort “link + run” check for FP4 (E2M1) matmul via cuBLASLt on `sm_121`.

Treat `CUBLAS_STATUS_NOT_SUPPORTED` as an informative result while the CUDA stack matures (DeepGEMM-style FP4 kernels may still need custom codepaths even when conversion helpers are present).

Observed on Spark0 (2026-05-09 / CUDA 13.0 `V13.0.88`): `cuda_cublaslt_fp4_smoke` returns `CUBLAS_STATUS_NOT_SUPPORTED` during heuristic selection.

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

## CCCL `cp.async.bulk` via `memcpy_async_tx` (CUTLASS-style bulk copies)

Some newer templated mainloops use `cp.async.bulk` rather than the older `cp.async` path, especially for larger transfers and more explicit completion mechanisms.

The probe `tools/cuda_probe/bin/cuda_sm121_cp_async_bulk_tx` is a tiny compile/run check that:

- includes CCCL’s internal `<cuda/__memcpy_async/memcpy_async_tx.h>`
- issues a 64-byte global->shared copy via `cuda::device::memcpy_async_tx` (which lowers to `cp.async.bulk` on SM90+)
- waits via `cuda::barrier` and validates the copied values

## Inline PTX `ldmatrix.sync` (CUTLASS-style gate)

CUTLASS and similar template kernels often rely on inline PTX for tensor-core data movement (e.g., `ldmatrix.sync` loads from shared memory).

The probe `tools/cuda_probe/bin/cuda_sm121_ldmatrix_smoke` is a tiny compile/run check that:

- emits `cvta.to.shared` + `ldmatrix.sync.aligned.m8n8.x4.shared.b16` inline PTX
- launches a single warp and checks the loaded registers are non-zero

Treat failures as an immediate blocker for CUTLASS-style kernels that rely on inline PTX mainloops.

## WMMA Tensor Core Smoke (CUTLASS-style proxy)

CUTLASS and other template GEMM libraries rely on tensor core matmul plumbing.

The probe `tools/cuda_probe/bin/cuda_sm121_wmma_smoke` is a tiny compile/run check that:

- includes `mma.h`
- runs a single warp WMMA matmul on `sm_121`
- prints a couple of output elements plus `max_abs_err` against an expected result

Observed on Spark0 (2026-05-12): `wmma_smoke ... max_abs_err=0`.

## Thread Block Clusters (CUTLASS-style scheduling)

Some newer templated kernels (including modern CUTLASS codepaths) can use thread-block clusters for scheduling and data movement.

The probe `tools/cuda_probe/bin/cuda_sm121_cluster_launch` is a tiny compile/run check that:

- queries `cudaDevAttrClusterLaunch` support
- uses `cudaLaunchKernelExC` + `cudaLaunchAttributeClusterDimension` to launch a 2-block cluster
- validates `cooperative_groups::this_cluster().block_rank()` via a device writeback

Observed on Spark0 (2026-05-12): `cluster_launch_supported=1`, `max_cluster_size_portable=8`, `max_active_clusters_for_2x1x1=48`.

### Cluster-Dims Attribute Note

CUDA also exposes a kernel-annotation syntax for clusters via `__cluster_dims__(x,y,z)` (often shown in the CUDA programming guide as an alternative to using `cudaLaunchKernelExC` attributes).

On some toolkit/architecture combinations, `nvcc -arch=sm_121` may reject `__cluster_dims__` at compile time even when runtime cluster launch via `cudaLaunchKernelExC` works.

The compile-only scripts `./scripts/cuda_probe_compile_only_spark0.sh` and `./scripts/cuda_probe_compile_only_tiny_spark0.sh`, plus the no-transfer `./scripts/cuda_probe_nvcc_minimal_spark0.sh`, include a standalone compile of a kernel annotated with `__cluster_dims__(2,1,1)` and print either `cluster_dims_attr_compile: OK` or the first lines of the compilation error.

Observed on Spark0 (2026-05-12): `cluster_dims_attr_compile: OK` (CUDA 13.0 `V13.0.88`).

## cuBLASLt FP8 Matmul Smoke

DeepGEMM and many CUTLASS kernels use FP8 inputs; a quick “works-first” gate is whether cuBLASLt can execute an FP8 GEMM on GB10.

The probes `tools/cuda_probe/bin/cuda_cublaslt_fp8_smoke` and `tools/cuda_probe/bin/cuda_cublaslt_fp8_e5m2_smoke` are tiny compile/run checks that:

- use FP8 E4M3 or E5M2 inputs for A/B (`CUDA_R_8F_E4M3` / `CUDA_R_8F_E5M2`)
- uses the narrow-precision-recommended “TN” format (A transposed, B non-transposed)
- accumulates into FP32 (`CUBLAS_COMPUTE_32F`) and writes BF16 output (`CUDA_R_16BF`)
- uses scalar scale pointers for A/B (scale=1) to keep the API surface minimal and match cuBLASLt narrow-precision conventions

Observed on Spark0 (2026-05-09): `cuBLASLt fp8 e4m3 smoke max_abs_err_vs_one=0`.
Observed on Spark0 (2026-05-09 / `cublasLtGetVersion=130101`): `cuda_cublaslt_fp8_e5m2_smoke` fails to find any supported algo even after trying `m=n=k` in `{16,64,128}` and workspace sizes `{1MiB,16MiB}`.
