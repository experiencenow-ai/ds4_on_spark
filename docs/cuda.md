# Cuda

> Supersedes: `docs/cuda-sm121.md`, `docs/cuda-implications.md`, `docs/cuda-expert-queue-dummy-benchmark.md`, `docs/cuda-probe.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 4 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `cuda-sm121.md`: CUDA 13 + `sm_121` Notes (367 lines).
- `cuda-implications.md`: CUDA Probe Implications (DeepGEMM / CUTLASS / cuBLASLt) (172 lines).
- `cuda-expert-queue-dummy-benchmark.md`: CUDA Expert Queue Dummy Benchmark (459 lines).
- `cuda-probe.md`: CUDA Probe Track (649 lines).

## Command Inventory

- `cuda-expert-queue-dummy-benchmark.md`: `./build-cuda/ds4_expert_queue_dummy --json --tokens 8 --topk 6 --experts 32 --hidden 64 --mid 128 --out 64 --iterations 2`
- `cuda-expert-queue-dummy-benchmark.md`: `./build-cuda/ds4_expert_queue_dummy --json --sorted --tokens 8 --topk 6 --experts 32 --hidden 64 --mid 128 --out 64 --iterations 2`
- `cuda-expert-queue-dummy-benchmark.md`: `./build-cuda/ds4_expert_queue_dummy --json --sorted --tokens 128 --topk 6 --experts 256 --route-experts 64 --hidden 128 --mid 256 --out 128 --iterations 4`
- `cuda-expert-queue-dummy-benchmark.md`: `./build-cuda/ds4_expert_queue_dummy --json --tokens 128 --topk 6 --experts 256 --hidden 128 --mid 256 --out 128 --iterations 8`
- `cuda-expert-queue-dummy-benchmark.md`: `./build-cuda-dummy/ds4_expert_queue_dummy --json --tokens 64 --topk 6 --experts 256 --hidden 128 --mid 256 --out 128 --iterations 4`
- `cuda-expert-queue-dummy-benchmark.md`: `./build-cuda-sorted-dummy/ds4_expert_queue_dummy --json --sorted \`
- `cuda-expert-queue-dummy-benchmark.md`: `make -C /tmp/ds4-tile-slices-compile CUDA_ARCH=sm_121 ds4_cuda.o`
- `cuda-expert-queue-dummy-benchmark.md`: `make -C /tmp/ds4-tile-slices-compile CUDA_ARCH=sm_121 ds4 ds4-bench`
- `cuda-expert-queue-dummy-benchmark.md`: `DS4_CUDA_SKIP_STARTUP_MODEL_CACHE=1 \`
- `cuda-expert-queue-dummy-benchmark.md`: `DS4_CUDA_WEIGHT_CACHE_LIMIT_GB=4 \`
- `cuda-expert-queue-dummy-benchmark.md`: `DS4_CUDA_WEIGHT_ARENA_CHUNK_MB=256 \`
- `cuda-expert-queue-dummy-benchmark.md`: `DS4_CUDA_MOE_BATCHED_EXPERT_SLICE_CACHE=1 \`
- `cuda-probe.md`: `./scripts/cuda_probe_sm121_gate_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_micro_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_minimal_gates_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_tiny_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_device_props_minimal_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_sm121_compile_report_tiny_minimal_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_cublaslt_tiny_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_capability_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_compile_only_tiny_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_tinyprops_sm121_compile_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_sm121_compile_probes_minimal_spark0.sh`
- `cuda-probe.md`: `./scripts/cuda_probe_kernel_launch_tiny_minimal_spark0.sh`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/cuda-sm121.md` | 367 | CUDA 13 + `sm_121` Notes | Build Flags, CUDA 13 `cudaDeviceProp` Layout Change, Verifying `nvcc` Arch Mapping, Separate Compilation / Device Link (`-rdc=true`), Device LTO (`-dlto`) |
| `docs/cuda-implications.md` | 172 | CUDA Probe Implications (DeepGEMM / CUTLASS / cuBLASLt) | GB10 / Spark0 Baseline, cuBLASLt, CUTLASS, Build Portability Notes (CUDA 13), DeepGEMM |
| `docs/cuda-expert-queue-dummy-benchmark.md` | 459 | CUDA Expert Queue Dummy Benchmark | Build, Run, Interpreting Output, Sorted Mode, Spark0 Smoke Result |
| `docs/cuda-probe.md` | 649 | CUDA Probe Track | Spark0: `sm_121` Gate (Fastest), Spark0: Micro Gate (No Repo Transfer; Single SSH), Spark0: Minimal Gates (nvcc + Device Props + `sm_121` Gate), Spark0: Tiny Smoke (Fast Path), Spark0: Device Props Minimal (No Repo Transfer) |
