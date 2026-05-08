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
  - `cuda_device_props` (runtime + device properties)
  - `cuda_sm121_probe` (sanity kernel compiled for `sm_121`)
  - `cuda_sm121_arch_report` (prints device CC + compiled `__CUDA_ARCH__`)
  - `cuda_cublaslt_smoke` (tiny cuBLASLt matmul smoke test)
  - `cuda_sm121_smem_optin` (shared-memory opt-in + dynamic shared memory launch)

Environment overrides:

- `SSH_OPTS`: forwarded to `ssh`
- `REMOTE_DIR`: where the probe directory lands on Spark0 (default: `/tmp/ds4_cuda_probe`)

## Spark0: Compile-Only `sm_121`

```bash
./scripts/cuda_probe_compile_only_spark0.sh
```

This is useful when kernel run is blocked but `nvcc` behavior needs confirmation.
It compiles `cuda_sm121_probe`, `cuda_sm121_arch_report`, `cuda_cublaslt_smoke`, and `cuda_sm121_smem_optin` for `sm_121`.

## Current Spark0 Results (2026-05-08)

Commands run:

```bash
./scripts/cuda_probe_compile_only_spark0.sh
./scripts/cuda_probe_spark0.sh
```

Observed:

- `nvcc` is CUDA 13.0 (`V13.0.88`)
- `-arch=sm_121` compiles and links (including `-lcublasLt`)
- Runtime launches a tiny `sm_121` kernel successfully
- cuBLASLt matmul smoke test succeeds (`max_abs_err=0`)
- Shared-memory opt-in probe succeeds; `MaxSharedMemoryPerBlockOptin=101376` bytes on GB10
- Device is reported as `NVIDIA GB10` with `cc=12.1`

Selected output excerpt:

```text
cudaDriverGetVersion=13000 cudaRuntimeGetVersion=13000
cudaGetDeviceCount=1
device[0]=NVIDIA GB10 cc=12.1 clock_khz=2418000 mem=128518373376
kernel wrote 0xc0d3cafe
kernel wrote magic=0xc0d3cafe __CUDA_ARCH__=1210
cuBLASLt sgemm smoke max_abs_err=0
max_smem_per_block_optin_bytes=101376
smem probe wrote 0x000000a5
```

## Where The Probe Lives

- Probe sources: `tools/cuda_probe/`
- Spark runner scripts: `scripts/cuda_probe*_spark0.sh`
