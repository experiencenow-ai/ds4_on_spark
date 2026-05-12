# CUDA Probe Track

This track keeps probe-only CUDA snippets that answer: “Can we compile for and run on GB10 (CC 12.1 / `sm_121`) with the installed CUDA toolkit?”

## Spark0: `sm_121` Gate (Fastest)

When you want the smallest “device-props + `sm_121` compile-only gates” set (ships `tools/cuda_probe/` to Spark0, but builds only `make sm121_gate`, plus a tiny `sm_121a` / `sm_121f` alias acceptance check via `cuda_sm121{a,f}_arch_list_report`):

```bash
./scripts/cuda_probe_sm121_gate_spark0.sh
```

This gate also includes a compile-only “fatbin packaging” probe using `-gencode arch=compute_121,code=[sm_121,compute_121]` when `nvcc --list-gpu-arch` is supported (quick confirmation that CUDA 13’s multi-code `-gencode` bracket-list spelling works for GB10 bring-up).

## Spark0: Tiny Smoke (Fast Path)

When you just need a quick “is CUDA alive + can we compile/run `sm_121`?” check:

```bash
./scripts/cuda_probe_tiny_spark0.sh
```

## Spark0: Device Props Minimal (No Repo Transfer)

When you want the one-line `schema=4` device summary without shipping `tools/cuda_probe/` to Spark0:

```bash
./scripts/cuda_probe_device_props_minimal_spark0.sh
```

This compiles a single tiny `.cu` file directly on Spark0 with `nvcc -arch=native` and prints the same `cuda drv=... schema=4` line as `tools/cuda_probe/bin/cuda_device_props_tiny`.

It also includes compile-only `-arch=sm_121`, `nvcc --gpu-architecture=sm_121`, and `nvcc --gpu-architecture=compute_121 --gpu-code=sm_121` gates so logs capture a direct “nvcc can target `sm_121`” signal even when you are not shipping `tools/cuda_probe/`.

To make the “end-to-end link+run via `sm_121`” path explicit (not just compile-only), run:

```bash
WITH_SM121_RUN=1 ./scripts/cuda_probe_device_props_minimal_spark0.sh
```

This additionally builds and runs the same tiny probe via `nvcc -arch=sm_121` and `nvcc --gpu-architecture=sm_121`.

To validate “PTX-only + driver JIT” for GB10 (toolchain emits `compute_121` PTX, Spark0 JITs to `sm_121`), run:

```bash
WITH_COMPUTE121_RUN=1 ./scripts/cuda_probe_device_props_minimal_spark0.sh
```

To validate “fatbin packaging” via explicit `-gencode` (embed both `sm_121` SASS and `compute_121` PTX), run:

```bash
WITH_GENCODE_RUN=1 ./scripts/cuda_probe_device_props_minimal_spark0.sh
```

When you specifically want a quick “does cuBLASLt build + run on `sm_121`?” gate:

```bash
./scripts/cuda_probe_cublaslt_tiny_spark0.sh
```

This includes additional “build-system flag spelling” variants for the same matmul smoke test (`--gpu-architecture=compute_121 --gpu-code=sm_121` and explicit `-gencode` for `sm_121` + `compute_121` PTX).

To capture a full log file on the Mac (without relying on `tee` + shell `pipefail`), set `LOG_PATH`:

```bash
LOG_PATH=/private/tmp/ds4_cuda_probe_tiny_$(date -u +%Y%m%d-%H%M%S).log ./scripts/cuda_probe_tiny_spark0.sh
```

This builds and runs only:

- `cuda_device_props_tiny` (one-line driver/runtime + key `device[0]` limits: clocks/memory/shared-mem/L2/threads/blocks/registers + driver-reserved shared memory + memory-pool support + cooperative/cluster launch support)
- `cuda_sm121_compile_probe.o` (compile-only gate; fails if the device pass does not see `__CUDA_ARCH__=1210`)
- `cuda_sm121_gpuarch_compile_probe.o` (compile-only gate for build systems that use `nvcc --gpu-architecture=sm_121`; fails if the device pass does not see `__CUDA_ARCH__=1210`)
- `cuda_sm121_gpuarch_code_compile_probe.o` (compile-only gate for build systems that split `nvcc --gpu-architecture=compute_121 --gpu-code=sm_121`; fails if the device pass does not see `__CUDA_ARCH__=1210`)
- `cuda_sm121_cxx20_flags_compile_probe.o` (compile-only gate for `-std=c++20 --extended-lambda --expt-relaxed-constexpr -arch=sm_121`; fails if the device pass does not see `__CUDA_ARCH__=1210`)
- `cuda_sm121_cxx20_flags_gpuarch_compile_probe.o` (compile-only gate for build systems that use `nvcc --gpu-architecture=sm_121` with C++20 flags; fails if the device pass does not see `__CUDA_ARCH__=1210`)
- `cuda_sm121_cluster_dims_attr_compile.o` (compile-only gate for `__cluster_dims__(...)` kernel annotations with `-arch=sm_121`; cluster/CUTLASS-style toolchain gate)
- `nvcc -gencode arch=compute_121,code=[sm_121,compute_121]` compile-only gate (runs when `nvcc --list-gpu-arch` is supported and advertises `compute_121`; fails if multi-code `-gencode` packaging is broken)
- `cuda_sm121_probe`
- `cuda_sm121_rdc_probe` (separate compilation + device link smoke test for `sm_121`)
- `cuda_sm121_dlto_probe` (device LTO (`-dlto`) smoke test for `sm_121`)
- `cuda_sm121_arch_report` (prints runtime device CC plus compiled `__CUDA_ARCH__` from an `sm_121` build; expected `1210`)
- `cuda_sm121_arch_list_report` (prints compile-time `__CUDA_ARCH_LIST__` plus CUDA 13 feature-set macros when defined; used to sanity-check which virtual-arch list `nvcc` believes it is compiling for)
- `cuda_sm121a_arch_list_report` / `cuda_sm121f_arch_list_report` (optional; best-effort build+run to observe CUDA 13 “variant arch spelling” behavior; may succeed even when `nvcc --list-gpu-code` does not advertise `sm_121a` / `sm_121f`)

To skip the separate-compilation and device-LTO link gates (faster / toolchain-only check), run:

```bash
WITH_LINK_PROBES=0 ./scripts/cuda_probe_tiny_spark0.sh
```

It also prints `nvcc --version` plus `--list-gpu-arch` / `--list-gpu-code` when supported (toolchain sanity gate for CUDA 13).

If `nvcc --list-gpu-arch` is supported, the script treats a missing `compute_121` entry as an error.

If `nvcc --list-gpu-code` is supported, the script treats a missing `sm_121` entry as an error (fast “toolchain cannot target GB10” signal).

Observed on Spark0 (2026-05-12): CUDA 13.0 `V13.0.88`; `nvcc --list-gpu-arch` includes `compute_121`; `nvcc --list-gpu-code` includes `sm_121`; `cuda_sm121_arch_report` prints `__CUDA_ARCH__=1210`; `cuda_sm121_arch_list_report` prints `__CUDA_ARCH_LIST__=1210` and reports `__CUDA_ARCH_SPECIFIC__=(missing)` / `__CUDA_ARCH_FAMILY_SPECIFIC__=(missing)` for `-arch=sm_121`; `cuda_sm121a_arch_list_report` / `cuda_sm121f_arch_list_report` both build+run successfully (even though `nvcc --list-gpu-code` does not list `sm_121a` / `sm_121f`) and also report those macros missing; `scripts/cuda_probe_nvcc_minimal_spark0.sh` PTX probes report `.target sm_121a` / `.target sm_121f` for `-arch=sm_121a` / `-arch=sm_121f` (and likewise for `compute_121a` / `compute_121f`); `cuda_sm121_rdc_probe` prints `rdc_probe in=0x12345678 out=0xb791f3de expect=0xb791f3de`; `cuda_sm121_dlto_probe` prints `dlto_probe in=0x12345678 out=0xce5cb9c3 expect=0xce5cb9c3`; `-gencode arch=compute_121,code=[sm_121,compute_121]` compile+run succeeds and embeds PTX (`cuobjdump --dump-ptx` reports `.target sm_121`).

Example (from `scripts/cuda_probe_nvcc_minimal_spark0.sh`):

- `cuda drv=13000 rt=13000 count=1 dev0="NVIDIA GB10" cc=12.1 mp=48 warp=32 clock_khz=2418000 mem_clock_khz=8533000 bus_width_bits=256 async_engines=1 mem=128518373376 smem_block=49152 smem_block_max=49152 smem_optin=101376 smem_sm=102400 smem_reserved_block=1024 l2=25165824 max_persisting_l2=18874368 max_apw=134217728 maxthr_block=1024 maxthr_sm=1536 maxblocks_sm=24 regs_block=65536 regs_sm=65536 mem_pools=1 coop_launch=1 cluster_launch=1 tma_map=1 cuda_arch=1210 schema=4`

If a queried `cudaDeviceGetAttribute` or driver-attribute field is unavailable (older runtime/toolkit/driver API, or CUDA headers too old to define the driver-attribute enum constant), the scripts print `-1` for that field rather than silently reporting `0`.

## Spark0: Capability Sweep (One Command)

When you want to run the key “is `sm_121` supported end-to-end?” checks in one shot:

```bash
./scripts/cuda_probe_capability_spark0.sh
```

To capture a full log file on the Mac (without relying on `tee` + shell `pipefail`), set `LOG_PATH`:

```bash
LOG_PATH=/private/tmp/ds4_cuda_probe_capability_$(date -u +%Y%m%d-%H%M%S).log ./scripts/cuda_probe_capability_spark0.sh
```

The capability sweep also sets per-step `REMOTE_DIR` values (including the cuBLASLt step) using a unique `REMOTE_TAG` so concurrent runs do not clobber `/tmp/ds4_cuda_probe_*` directories on Spark0. To make the remote directory names deterministic (useful for debugging), set:

```bash
REMOTE_TAG=manual ./scripts/cuda_probe_capability_spark0.sh
```

This runs, in order:

- `scripts/cuda_probe_nvcc_minimal_spark0.sh` (no repo transfer)
- `scripts/cuda_probe_device_props_minimal_spark0.sh` (no repo transfer; one-line `schema=4` device summary + `sm_121` compile gates + end-to-end `-arch=sm_121` / `nvcc --gpu-architecture=sm_121` build+run; best-effort `-arch=compute_121` and `-gencode` build+run)
- `scripts/cuda_probe_cmake_minimal_spark0.sh` (no repo transfer; CMake build-system gate)
- `scripts/cuda_probe_tiny_spark0.sh` (tiny build+run)
- `scripts/cuda_probe_compile_only_tiny_spark0.sh` (variant + PTX-embed probes)
- `scripts/cuda_probe_cublaslt_tiny_spark0.sh` (cuBLASLt matmul smoke tests; includes FP8/FP4 best-effort probes)
- `scripts/cuda_probe_kernel_tiny_spark0.sh` (kernel plumbing gates; no cuBLASLt)

To skip the “kernel plumbing” bring-up gates (faster), run:

```bash
WITH_KERNEL_TINY=0 ./scripts/cuda_probe_capability_spark0.sh
```

To skip the cuBLASLt smoke gates (faster / kernel-only), run:

```bash
WITH_CUBLASLT_TINY=0 ./scripts/cuda_probe_capability_spark0.sh
```

To skip the CMake build-system gate (faster), run:

```bash
WITH_CMAKE_MINIMAL=0 ./scripts/cuda_probe_capability_spark0.sh
```

To skip the device-props minimal gate (faster), run:

```bash
WITH_DEVICE_PROPS_MINIMAL=0 ./scripts/cuda_probe_capability_spark0.sh
```

To keep the device-props “`sm_121` end-to-end” builds off (compile-only gates still run), set:

```bash
WITH_DEVICE_PROPS_SM121_RUN=0 ./scripts/cuda_probe_capability_spark0.sh
```

To skip the best-effort `-arch=compute_121` “PTX-only + driver JIT” build+run inside the device-props step, set:

```bash
WITH_DEVICE_PROPS_COMPUTE121_RUN=0 ./scripts/cuda_probe_capability_spark0.sh
```

To skip the best-effort explicit `-gencode` fatbin build+run inside the device-props step, set:

```bash
WITH_DEVICE_PROPS_GENCODE_RUN=0 ./scripts/cuda_probe_capability_spark0.sh
```

Observed on Spark0 (2026-05-12): `scripts/cuda_probe_capability_spark0.sh` completes end-to-end on CUDA 13.0 `V13.0.88`, including NVRTC (`supportedArchs` includes `121`), nvJitLink, TMA tensor-map encode, and cluster launch probes.

## Spark0: Tiny Compile-Only `sm_121`

When you only need to validate `nvcc` / toolchain support for `-arch=sm_121`:

```bash
./scripts/cuda_probe_compile_only_tiny_spark0.sh
```

To capture a full log file on the Mac (without relying on `tee` + shell `pipefail`), set `LOG_PATH`:

```bash
LOG_PATH=/private/tmp/ds4_cuda_probe_compile_only_tiny_$(date -u +%Y%m%d-%H%M%S).log ./scripts/cuda_probe_compile_only_tiny_spark0.sh
```

This also performs best-effort toolchain-only checks when supported:

- Always attempt best-effort compile-only builds for `sm_121a` / `sm_121f`, and report whether each target was advertised by `nvcc --list-gpu-code` (informational; the hard failure remains missing `sm_121` support).
- Also attempt the same `sm_121a` / `sm_121f` compile-only probes via the long-form `nvcc --gpu-architecture=...` flag (informational; build-system compatibility check).
- If `nvcc --list-gpu-arch` advertises `compute_121`, attempt a compile-only build for `-arch=compute_121` (virtual-arch / PTX-target probe).
- Attempt best-effort feature-set macro compile-only probes for `-arch=compute_121a` and `-arch=compute_121f` (informational; validates `__CUDA_ARCH_SPECIFIC__` / `__CUDA_ARCH_FAMILY_SPECIFIC__` macro definitions when those targets are accepted by the toolchain).
- Print a best-effort `__CUDA_ARCH_LIST__` snapshot for `-arch=sm_121`, `-arch=sm_121a`, and `-arch=sm_121f` to make NVCC’s implicit “virtual arch list” observable in logs.
- If `nvcc --list-gpu-arch` advertises `compute_121`, attempt compile-only `-gencode` builds for `arch=compute_121,code=sm_121`, `arch=compute_121,code=compute_121`, and `arch=compute_121,code=[sm_121,compute_121]` (multi-target build plumbing gate + bracket-list syntax probe).
- Attempt a standalone compile of a kernel annotated with `__cluster_dims__(2,1,1)` and print `cluster_dims_attr_compile: OK` or the first lines of the compile error (some toolkits reject the annotation for `sm_121` even when runtime cluster launch works).
- If `cuobjdump` is available, emit a `-fatbin` with `-arch=sm_121` and confirm an embedded PTX section exists (`cuobjdump --dump-ptx`).
- If `cuobjdump` is available and `compute_121` is advertised, emit `-fatbin` artifacts with explicit `-gencode` (`code=sm_121` only, `code=compute_121` only, and `sm_121+compute_121` via both repeated `-gencode` and bracket-list `code=[sm_121,compute_121]`) and report whether embedded PTX is present (expected: SM-only missing; PTX-only present; SM+PTX present).
- If `cuobjdump` is available, emit a `-fatbin` with `-arch=native` and report whether an embedded PTX section exists (expected missing per `nvcc` docs).
- When PTX is present, the script also prints the first PTX `.target` line (`ptx_target_*`) so the embedded PTX arch is explicit in logs.

## Spark0: Minimal `nvcc` Compile + Run (No Repo Transfer)

When you want a completely self-contained check that does not ship `tools/cuda_probe/`:

```bash
./scripts/cuda_probe_nvcc_minimal_spark0.sh
```

This script writes a tiny CUDA file directly into a Spark0 temp directory, then:

- Runs best-effort compile-only probes for `-arch=sm_121` plus `sm_121a` / `sm_121f` (variant targets) and `compute_121` (when advertised) (fast toolchain signal; no kernel run required; prints first error lines on failure)
- Runs best-effort feature-set macro compile-only probes for `-arch=compute_121a` and `-arch=compute_121f` (informational; validates `__CUDA_ARCH_SPECIFIC__` / `__CUDA_ARCH_FAMILY_SPECIFIC__` macro definitions when those targets are accepted)
- Prints a best-effort `__CUDA_ARCH_LIST__` snapshot for `-arch=sm_121`, `-arch=sm_121a`, and `-arch=sm_121f` to make NVCC’s implicit “virtual arch list” observable in logs
- Runs a best-effort compile-only probe using `nvcc --gpu-architecture=sm_121` (long-form flag used by some build systems)
- Runs a best-effort compile-only probe with `-std=c++20 --extended-lambda --expt-relaxed-constexpr` for `-arch=sm_121` (and `compute_121` when advertised) as a CUTLASS/DeepGEMM-style toolchain gate (no repo transfer)
- Prints `ptxas --version` and `nvlink --version` when present, and emits a `-Xptxas=-v` compile-only snippet for `-arch=sm_121` (useful when diagnosing toolchain mismatches)
- Attempts a standalone compile of a kernel annotated with `__cluster_dims__(2,1,1)` and prints `cluster_dims_attr_compile: OK` or the first lines of the compile error
- Runs best-effort compile-only `-gencode` probes for `arch=compute_121,code=sm_121`, `arch=compute_121,code=compute_121`, and `arch=compute_121,code=[sm_121,compute_121]` when `compute_121` is advertised (multi-target build plumbing gate + bracket-list syntax probe)
- If `cuobjdump` is available and `compute_121` is advertised, emits `-fatbin` artifacts with explicit `-gencode` (`code=sm_121` only, `code=compute_121` only, and `sm_121+compute_121` via repeated `-gencode`) and reports whether embedded PTX is present (expected: SM-only missing; PTX-only present; SM+PTX present).
- Compiles and runs it with `-arch=sm_121`, `--gpu-architecture=sm_121`, and `-arch=native`
- If `compute_121` is advertised, also compiles and runs a PTX-targeted build via `-arch=compute_121` (verifies that driver/runtime JIT can execute `compute_121` PTX on GB10)
- If `compute_121` is advertised, also does a best-effort compile+run via `-gencode arch=compute_121,code=[sm_121,compute_121]` and includes it in the embedded-PTX report (multi-target build-system syntax probe)
- Always attempts best-effort compile+run for `-arch=sm_121a` and `-arch=sm_121f` (variant targets), and reports whether each target was advertised by `nvcc --list-gpu-code` (`advertised=yes/no/unknown`) (informational; missing `sm_121` remains the hard failure)
- Runs a best-effort cross-translation-unit `__global__` template explicit-instantiation link probe and prints `template_stub_default` / `template_stub_stubfalse` / `template_stub_rdc` (CUDA 13 `-static-global-template-stub` behavior gate for CUTLASS/DeepGEMM-style builds)
- Prints a `cuda_device_props_tiny`-schema one-line driver/runtime + key `device[0]` limits (CC/SMs/clocks/memory/shared-mem/L2/threads/blocks/registers + cooperative/cluster launch support)
  - Includes driver-reserved shared memory per block (`cudaDevAttrReservedSharedMemoryPerBlock`) plus `cudaMallocAsync`/memory-pool support (`cudaDevAttrMemoryPoolsSupported`) when available.
- Prints the device-observed `__CUDA_ARCH__`
- If `cuobjdump` is available, reports whether each binary contains embedded PTX (expected: `sm_121` present, `gpuarch_sm_121` present, `native` missing; `compute_121` present when built)

## Spark0: Minimal CMake Configure + Build + Run (No Repo Transfer)

When you want to validate that a typical CMake CUDA project can target GB10 (`sm_121`) using `CMAKE_CUDA_ARCHITECTURES`:

```bash
./scripts/cuda_probe_cmake_minimal_spark0.sh
```

This script writes a tiny `CMakeLists.txt` + `main.cu` directly into a Spark0 temp directory, then:

- Prints `cmake --version` and fails if `cmake` is missing or older than 3.18 (first version with `CMAKE_CUDA_ARCHITECTURES`)
- Prints `nvcc --version`
- Configures/builds/runs the same tiny executable with:
  - `-DCMAKE_CUDA_ARCHITECTURES="121"` (real + virtual; SASS + PTX)
  - `-DCMAKE_CUDA_ARCHITECTURES="121-real"` (real-only; SASS-only)
  - `-DCMAKE_CUDA_ARCHITECTURES="121-virtual"` (virtual-only; PTX-only + driver JIT)
  - `-DCMAKE_CUDA_ARCHITECTURES="native"` when `cmake >= 3.24` (Spark0 GPU arch autodetect)
- For each case, prints the `--generate-code` lines from the verbose build log (best-effort) and runs the executable (expects `__CUDA_ARCH__=1210`)

Observed on Spark0 (2026-05-12, `cmake 3.28.3`, `nvcc` CUDA 13.0 `V13.0.88`):

- `CMAKE_CUDA_ARCHITECTURES="121"`: `--generate-code=arch=compute_121,code=[compute_121,sm_121]` (PTX + SASS)
- `CMAKE_CUDA_ARCHITECTURES="121-real"`: `--generate-code=arch=compute_121,code=[sm_121]` (SASS-only)
- `CMAKE_CUDA_ARCHITECTURES="121-virtual"`: `--generate-code=arch=compute_121,code=[compute_121]` (PTX-only)
- `CMAKE_CUDA_ARCHITECTURES="native"`: `nvcc -arch=native` (no explicit `--generate-code` line in the build log)

All four cases run and print `__CUDA_ARCH__=1210` on GB10.

Environment overrides:

- `SSH_OPTS`: forwarded to `ssh`
- `REMOTE_DIR`: where the temp project is created on Spark0 (default: `/tmp/ds4_cuda_probe_cmake_minimal`)

## Spark0: Kernel Bring-up Tiny (CUTLASS/DeepGEMM Gates)

When you want a small, focused “kernel plumbing” gate set (no cuBLASLt) that is still representative for CUTLASS/DeepGEMM-style kernels:

```bash
./scripts/cuda_probe_kernel_tiny_spark0.sh
```

To capture a full log file on the Mac (without relying on `tee` + shell `pipefail`), set `LOG_PATH`:

```bash
LOG_PATH=/private/tmp/ds4_cuda_probe_kernel_tiny_$(date -u +%Y%m%d-%H%M%S).log ./scripts/cuda_probe_kernel_tiny_spark0.sh
```

This builds and runs a curated subset of probes (all `sm_121` unless noted):

- `cuda_device_props_tiny`
- `cuda_sm121_compile_probe.o` (compile-only gate)
- `cuda_sm121_gpuarch_compile_probe.o` (compile-only gate for `nvcc --gpu-architecture=sm_121`)
- `cuda_sm121_gpuarch_code_compile_probe.o` (compile-only gate for `nvcc --gpu-architecture=compute_121 --gpu-code=sm_121`)
- `cuda_sm121_cxx20_flags_compile_probe.o` (compile-only gate for `-std=c++20 --extended-lambda --expt-relaxed-constexpr -arch=sm_121`)
- `cuda_sm121_cxx20_flags_gpuarch_compile_probe.o` (compile-only gate for `nvcc --gpu-architecture=sm_121` with C++20 flags)
- `cuda_sm121_arch_report` (runtime CC + compiled `__CUDA_ARCH__`)
- `cuda_sm121_arch_list_report` (`__CUDA_ARCH_LIST__` + CUDA 13 feature macro sanity)
- `cuda_sm121_rdc_probe` (separate compilation + device link smoke test for `sm_121`)
- `cuda_sm121_dlto_probe` (device LTO (`-dlto`) smoke test for `sm_121`)
- `cuda_sm121_smem_optin` (shared-memory opt-in + max dynamic shared-memory launch gate)
- `cuda_sm121_devattrs` (device attribute dump for kernel bring-up gating)
- `cuda_sm121_pipeline_memcpy_async` (cp.async-style global->shared copy)
- `cuda_sm121_cp_async_bulk_tx` (explicit `cp.async.bulk` global->shared copy via CCCL)
- `cuda_sm121_tma_bulk_tensor_1d` (TMA `cp.async.bulk.tensor.1d` load via `cuTensorMapEncodeTiled`)
- `cuda_sm121_tma_bulk_tensor_2d` (TMA `cp.async.bulk.tensor.2d` load via `cuTensorMapEncodeTiled`)
- `cuda_sm121_ldmatrix_smoke` (inline PTX `ldmatrix.sync` gate)
- `cuda_sm121_wmma_smoke` (WMMA plumbing proxy)
- `cuda_sm121_cxx20_probe` (C++20 toolchain gate)
- `cuda_sm121_nvcc_flags_probe` (`-std=c++20` + `--extended-lambda` + `--expt-relaxed-constexpr` gate)
- `cuda_sm121_nvrtc_jit` / `cuda_sm121_nvrtc_cxx20_jit` (NVRTC → PTX → Driver API module load/launch gates)
- `cuda_sm121_nvjitlink_jit` (NVRTC → PTX → nvJitLink → CUBIN → Driver API module load/launch gate)
- Best-effort: build+run `cuda_sm121_fatbin_probe` with `-arch=sm_121a` / `-arch=sm_121f` and with `nvcc --gpu-architecture=sm_121a` / `sm_121f` (variant acceptance + runtime `__CUDA_ARCH__`/`__CUDA_ARCH_LIST__` sanity)

The runner retries each probe once on failure to smooth over transient Spark0 GPU pressure (for example, primary-context init failures that surface as “out of memory”).

Observed on Spark0 (2026-05-12): CUDA 13.0 `V13.0.88`; `nvcc --list-gpu-code` includes `sm_121` (no `sm_121a` / `sm_121f` entries observed); best-effort build+run of `cuda_sm121_fatbin_probe` via `-arch=sm_121a` / `-arch=sm_121f` and `--gpu-architecture=sm_121a` / `sm_121f` succeeds and reports `__CUDA_ARCH_LIST__=1210` and kernel `__CUDA_ARCH__=1210`; feature-set macro compile reports for `-arch=compute_121a` / `-arch=compute_121f` report `__CUDA_ARCH_SPECIFIC__=(missing)` / `__CUDA_ARCH_FAMILY_SPECIFIC__=(missing)` (treat as “flags accepted, macros not surfaced” until a newer toolkit proves otherwise); `scripts/cuda_probe_nvcc_minimal_spark0.sh` reports embedded PTX for `-arch=sm_121a` / `-arch=sm_121f` builds, and the first PTX `.target` line remains `.target sm_121` (so the variant suffix does not currently imply a distinct embedded-PTX target for portability planning); `cuda_sm121_cxx20_probe` reports `__CUDA_ARCH__=1210`; `cuda_sm121_smem_optin` reports `MaxSharedMemoryPerBlockOptin=101376` and passes; `cuda_sm121_tma_bulk_tensor_2d` returns `rc=0`; NVRTC `supportedArchs` includes `121`.

## Spark0: Compile + Run

From the Mac (this repo checkout):

```bash
./scripts/cuda_probe_spark0.sh
```

To capture a full log file on the Mac (without relying on `tee` + shell `pipefail`), set `LOG_PATH`:

```bash
LOG_PATH=/private/tmp/ds4_cuda_probe_spark0_$(date -u +%Y%m%d-%H%M%S).log ./scripts/cuda_probe_spark0.sh
```

What it does:

- Ships `tools/cuda_probe/` to Spark0 (no remote git clone required).
- Uses `tar --no-xattrs` (and `--no-mac-metadata` on `bsdtar`) + `LC_ALL=C` to avoid macOS xattr/provenance noise during transfer.
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
  - `cuda_cublaslt_fp8_e5m2_sweep` (sweep E5M2 configs to see whether any cuBLASLt path is supported)
  - `cuda_cublaslt_fp4_smoke` (tiny cuBLASLt FP4 (E2M1) matmul smoke test; best-effort capability probe)
  - `cuda_cublaslt_fp4_sweep` (sweep FP4 configs to see whether any cuBLASLt path is supported)
  - `cuda_sm121_smem_optin` (shared-memory opt-in + dynamic shared memory launch)
  - `cuda_sm121_devattrs` (device attribute dump for kernel bring-up gating)
  - `cuda_sm121_fp8_conv` (`cuda_fp8.h` conversion probe for FP8 plumbing)
  - `cuda_sm121_bf16_conv` (`cuda_bf16.h` conversion probe for BF16 plumbing; CUTLASS/DeepGEMM-style gate)
  - `cuda_sm121_fp4_conv` (`cuda_fp4.h` conversion probe for FP4 (E2M1) plumbing)
  - `cuda_sm121_pipeline_memcpy_async` (`__pipeline_memcpy_async` global->shared copy probe)
  - `cuda_sm121_barrier_memcpy_async` (`cuda::barrier` + `cuda::memcpy_async` copy probe)
  - `cuda_sm121_cp_async_bulk_tx` (explicit `cp.async.bulk` global->shared copy via CCCL `cuda::device::memcpy_async_tx`)
  - `cuda_sm121_tma_bulk_tensor_1d` (TMA `cp.async.bulk.tensor.1d` load via `cuTensorMapEncodeTiled` + `cuda::device::experimental::cp_async_bulk_tensor_1d_global_to_shared`)
  - `cuda_sm121_tma_bulk_tensor_2d` (TMA `cp.async.bulk.tensor.2d` load via `cuTensorMapEncodeTiled` + `cuda::device::experimental::cp_async_bulk_tensor_2d_global_to_shared`)
  - `cuda_sm121_cccl_atomic_ref` (CCCL `cuda::atomic_ref` device-scope + block-scope atomics)
  - `cuda_sm121_cuda_graph_smoke` (CUDA graph capture → instantiate → launch smoke test)
  - `cuda_sm121_nvrtc_jit` (NVRTC compile-to-PTX + Driver API module load/launch for `compute_121`)
  - `cuda_sm121_nvrtc_cxx20_jit` (NVRTC `--std=c++20` compile-to-PTX + Driver API module load/launch for `compute_121`)
  - `cuda_sm121_nvcc_flags_probe` (nvcc `-std=c++20` + `--extended-lambda` + `--expt-relaxed-constexpr` compile/run gate for `sm_121`)
  - `cuda_sm121_nvjitlink_jit` (NVRTC compile-to-PTX + nvJitLink PTX→CUBIN + Driver API module load/launch for `sm_121`)
  - `cuda_sm121_cxx20_probe` (`-std=c++20` toolchain probe; DeepGEMM-style build gate)
  - `cuda_sm121_ldmatrix_smoke` (inline PTX `ldmatrix.sync` smoke test; CUTLASS-style inline-PTX gate)
  - `cuda_sm121_wmma_smoke` (`mma.h` WMMA matmul smoke test; CUTLASS-style proxy)
  - `cuda_sm121_cluster_launch` (thread-block cluster launch + `cooperative_groups::this_cluster().block_rank()` smoke test)

Environment overrides:

- `SSH_OPTS`: forwarded to `ssh`
- `REMOTE_DIR`: where the probe directory lands on Spark0 (default: `/tmp/ds4_cuda_probe`)
- `LOG_PATH`: where to append a complete local log file on the Mac

## Spark0: Compile-Only `sm_121`

```bash
./scripts/cuda_probe_compile_only_spark0.sh
```

To capture a full log file on the Mac (without relying on `tee` + shell `pipefail`), set `LOG_PATH`:

```bash
LOG_PATH=/private/tmp/ds4_cuda_probe_compile_only_spark0_$(date -u +%Y%m%d-%H%M%S).log ./scripts/cuda_probe_compile_only_spark0.sh
```

This is useful when kernel run is blocked but `nvcc` behavior needs confirmation.
It prints `nvcc --list-gpu-arch` / `nvcc --list-gpu-code` when supported, then compiles `cuda_sm121_compile_probe.o`, `cuda_sm121_probe`, `cuda_sm121_rdc_probe`, `cuda_sm121_fatbin_probe`, `cuda_sm121_dlto_probe`, `cuda_sm121_arch_report`, `cuda_cublaslt_smoke`, `cuda_cublaslt_fp8_smoke`, `cuda_cublaslt_fp8_e5m2_smoke`, `cuda_cublaslt_fp8_e5m2_sweep`, `cuda_cublaslt_fp4_smoke`, `cuda_cublaslt_fp4_sweep`, `cuda_sm121_smem_optin`, `cuda_sm121_devattrs`, `cuda_sm121_fp8_conv`, `cuda_sm121_bf16_conv`, `cuda_sm121_fp4_conv`, `cuda_sm121_pipeline_memcpy_async`, `cuda_sm121_barrier_memcpy_async`, `cuda_sm121_cp_async_bulk_tx`, `cuda_sm121_tma_bulk_tensor_1d`, `cuda_sm121_tma_bulk_tensor_2d`, `cuda_sm121_cccl_atomic_ref`, `cuda_sm121_cxx20_probe`, `cuda_sm121_nvcc_flags_probe`, `cuda_sm121_ldmatrix_smoke`, `cuda_sm121_wmma_smoke`, `cuda_sm121_cluster_launch`, `cuda_sm121_nvrtc_jit`, `cuda_sm121_nvrtc_cxx20_jit`, and `cuda_sm121_nvjitlink_jit` for `sm_121`, plus `cuda_sm120_compat_probe` for `sm_120`.
It also compiles `cuda_sm121_cuda_graph_smoke` (CUDA graph capture/launch smoke test) for `sm_121`.
Finally, it attempts a standalone `nvcc -arch=sm_121` compile of a kernel using the `__cluster_dims__` attribute (`tools/cuda_probe/src/cuda_sm121_cluster_dims_attr_compile.cu`) and prints whether it compiled or the first lines of the error output.

## Spark0: Disassemble (`cuobjdump` / `nvdisasm`)

```bash
./scripts/cuda_probe_disasm_spark0.sh
```

To capture a full log file on the Mac (without relying on `tee` + shell `pipefail`), set `LOG_PATH`:

```bash
LOG_PATH=/private/tmp/ds4_cuda_probe_disasm_spark0_$(date -u +%Y%m%d-%H%M%S).log ./scripts/cuda_probe_disasm_spark0.sh
```

This script builds a small subset of the probes and then dumps the first lines of:

- `cuobjdump --dump-sass` output (to confirm the toolkit can decode `sm_121` SASS)
- `nvdisasm` output (to confirm the disassembler recognizes `sm_121`)

Currently it disassembles:

- `cuda_sm121_probe`
- `cuda_sm121_cp_async_bulk_tx`
- `cuda_sm121_tma_bulk_tensor_2d`
- `cuda_sm121_ldmatrix_smoke` (inline PTX `ldmatrix.sync`)
- `cuda_sm121_wmma_smoke` (WMMA / tensor core proxy)

This is useful when bringing up CUTLASS/DeepGEMM-style kernels, because it validates that the developer tooling can inspect the generated kernels on Spark0.

## Current Spark0 Results (2026-05-12)

Commands run:

```bash
./scripts/cuda_probe_capability_spark0.sh spark0@aitopatom-9ab9.local
```

Observed:

- `nvcc` is CUDA 13.0 (`V13.0.88`)
- `ptxas` and `nvlink` report CUDA 13.0 (`V13.0.88`) when present (useful to catch mixed-toolchain hosts)
- `nvcc --list-gpu-arch` includes `compute_121` when supported
- `nvcc --list-gpu-code` includes `sm_121` when supported
- `nvcc -arch=compute_121 -c` compile-only probe succeeds when `compute_121` is advertised (toolchain PTX-target gate)
- `cluster_dims_attr_compile: OK` for a kernel annotated with `__cluster_dims__(2,1,1)` (toolchain accepts cluster annotations for `sm_121`)
- `cuobjdump --dump-ptx` shows PTX embedded for `-arch=sm_121`, and missing for `-arch=native` (expected portability signal)
- `nvcc --gpu-architecture=sm_121` compiles, links, and runs the minimal probe (schema line includes `cuda_arch=1210`; PTX embedded)
- CMake config/build/run with `CMAKE_CUDA_ARCHITECTURES="121"` prints `__CUDA_ARCH__=1210`
- When PTX is present, scripts also print the first PTX `.target` line (`ptx_target_*`) for quick arch verification.
- Device is reported as `NVIDIA GB10` with `cc=12.1`
- `cuda_sm121_compile_probe.o` compile gate observes `__CUDA_ARCH__=1210` for `-arch=sm_121`
- The kernel-tiny subset (no cuBLASLt) compiles and runs end-to-end, and retries once to smooth over transient Spark0 GPU pressure

## Full Suite Spark0 Results (2026-05-11)

Commands run:

```bash
./scripts/cuda_probe_compile_only_spark0.sh spark0@aitopatom-9ab9.local
./scripts/cuda_probe_spark0.sh spark0@aitopatom-9ab9.local
```

Observed:

- `nvcc` is CUDA 13.0 (`V13.0.88`)
- `-arch=sm_121` compiles and links (including `-lcublasLt`)
- `cuobjdump --dump-sass` and `nvdisasm` decode `sm_121` binaries on Spark0 (see `./scripts/cuda_probe_disasm_spark0.sh`)
- `nvcc -arch=sm_121` accepts the `__cluster_dims__` kernel annotation (compile-only check prints `cluster_dims_attr_compile: OK`)
- `-arch=sm_120` binaries run on GB10 (`sm_121`) successfully (probe prints `__CUDA_ARCH__=1200` on device `cc=12.1`)
- Runtime launches a tiny `sm_121` kernel successfully
- Separate compilation (`-dc`) + device link (`-dlink`) succeeds for `sm_121` (`cuda_sm121_rdc_probe` runs and validates output)
- Device LTO (`-dlto`) compile/run succeeds for `sm_121` (`cuda_sm121_dlto_probe` runs and validates output)
- cuBLASLt matmul smoke test succeeds (`max_abs_err=0`)
- cuBLASLt FP8 matmul smoke test succeeds (`max_abs_err_vs_one=0`)
- cuBLASLt FP8 (E5M2) matmul smoke probe fails to find any supported algo on Spark0 (CUDA 13.0 `V13.0.88`) even after trying `m=n=k` in `{16,64,128}` and workspace sizes `{1MiB,16MiB}` using the narrow-precision-recommended “TN” format (A transposed, B non-transposed) and BF16 output (the Spark runner continues past this failure; observed `cublasLtGetVersion=130101`)
- cuBLASLt FP8 (E5M2) sweep returns `CUBLAS_STATUS_NOT_SUPPORTED` across BF16/F16/F32 output dtypes and `CUBLAS_COMPUTE_32F` / `CUBLAS_COMPUTE_32F_FAST_TF32` (observed `cublasLtGetVersion=130101`)
- cuBLASLt FP4 (E2M1) heuristic selection succeeds for BF16 output (`cuda_cublaslt_fp4_sweep` prints `heuristic=CUBLAS_STATUS_SUCCESS got=8 rc=0`), but the current “identity×ones” numeric check in `cuda_cublaslt_fp4_smoke` still reports `max_abs_err_vs_one=1` (treat FP4 as “execution path exists”, not “numerically validated”, until we wire a correct NVFP4 pack/scale recipe)
- Shared-memory opt-in probe succeeds; `MaxSharedMemoryPerBlockOptin=101376` bytes on GB10
- FP8 conversion probe succeeds (`fp8_conv ... halfraw_e4m3=0x3d00`)
- BF16 conversion probe succeeds (`cuda_bf16.h` conversions compile and run for `sm_121`)
- FP4 conversion probe succeeds (`fp4_conv ... halfraw_e2m1=0x3c00`)
- Pipeline memcpy-async probe succeeds (cp.async-style global->shared copy)
- Barrier memcpy-async probe succeeds (`cuda::barrier` + `cuda::memcpy_async`)
- Explicit `cp.async.bulk` (CCCL `memcpy_async_tx`) probe succeeds (`cuda_sm121_cp_async_bulk_tx`)
- TMA bulk-tensor probe succeeds (`cuda_sm121_tma_bulk_tensor_1d` uses `cuTensorMapEncodeTiled` + `cp.async.bulk.tensor`)
- TMA bulk-tensor probe succeeds (`cuda_sm121_tma_bulk_tensor_2d` uses `cuTensorMapEncodeTiled` + `cp.async.bulk.tensor`)
- CCCL atomic-ref probe succeeds (`cuda::atomic_ref`)
- CUDA graph smoke probe succeeds (stream capture + instantiate + launch)
- NVRTC JIT probe succeeds (`nvrtc supportedArchs` includes `121`; driver loads PTX and launches kernel)
- NVRTC JIT probe succeeds in C++20 mode (`--std=c++20` for `compute_121`; probe prints `nvrtc_cxx20_jit ok out=0x1234567a`)
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
cublasLtGetVersion=130101 cublasLtGetCudartVersion=13000
cuBLASLt fp8 e5m2 probe try m=128 n=128 k=128 ws_bytes=16777216
cuBLASLt fp8 e5m2 smoke: no supported configuration found
(cuda_cublaslt_fp8_e5m2_smoke failed; continuing)
cuBLASLt fp4 e2m1 smoke max_abs_err_vs_one=1
fp4_e2m1 sweep ws_bytes=1048576 D=CUDA_R_16BF compute=CUBLAS_COMPUTE_32F heuristic=CUBLAS_STATUS_SUCCESS got=8 rc=0
max_smem_per_block_optin_bytes=101376
smem probe wrote 0x000000a5
fp8_conv x=1.250000 e4m3=0x3a e5m2=0x3d halfraw_e4m3=0x3d00 halfraw_e5m2=0x3d00
bf16_conv x=1.250000 raw_x=0x3fa0 x_back=1.250000 y=-2.500000 raw_y=0xc020 y_back=-2.500000 v_back=(1.250000,-2.500000)
fp4_conv x=1.250000 e2m1_storage=0x02 e2m1_nibble=0x2 halfraw_e2m1=0x3c00
pipeline_memcpy_async out=11111111 22222222 33333333 44444444
barrier_memcpy_async ok first=decaf000 last=decaf01f
tma_bulk_tensor_1d rc=0 out0=00 out127=7f
tma_bulk_tensor_2d rc=0 out0=00 out127=7f
cluster_dims_attr_compile: OK
cuda_graph_smoke out=22222222
nvrtcVersion=13.0
nvrtc supportedArchs: 75 80 86 87 88 89 90 100 103 110 120 121
nvrtc_jit ok out=0x12345679
nvrtc_cxx20_jit ok out=0x1234567a
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
