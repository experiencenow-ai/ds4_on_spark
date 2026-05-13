# Build Skeleton Overview

This repo’s build-skeleton track provides a conservative C/CUDA foundation for DS4-on-Spark:

- C11 library target (`ds4`) with optional CUDA integration
- Static-allocation patterns (arena + fixed pools/rings)
- Minimal logging with pluggable sinks (including a fixed-size ring capture)
- Config parsing/loading from memory/file/env (with diagnostics helpers)
- CUDA wrappers that compile on macOS (stubbed when CUDA is disabled)
- Unit-test scaffolding runnable on macOS (CPU-only)

## Layout

- `CMakeLists.txt`: Library/CLI/tests wiring; CUDA is `OFF` by default on macOS.
- `Makefile`: Thin wrappers for the common CMake/CTest commands (see `docs/build.md`).
- `include/ds4/*.h`: Public API headers.
- `src/*.c`, `src/*.cu`: DS4 implementation.
- `tests/*.c`: Unit tests; driven by `tests/test_main.c`.
- `cmake/*.cmake`: Reusable CMake helpers and smoke tests.

## Static allocation patterns

The build skeleton avoids heap allocation in core paths. The primary pattern is:

- `ds4_arena_t`: Caller-provided arena backing (`include/ds4/arena.h`, `src/ds4_arena.c`)
- `ds4_cuda_arena_t`: Optional bump allocator for a single `cudaMalloc` region (`include/ds4/cuda_arena.h`, `src/ds4_cuda_arena.c`)
- `ds4_ctx_t`: One “context” object that carries config, arena, optional log capture, and an optional CUDA arena (`include/ds4/ds4.h`, `src/ds4.c`)

`ds4_ctx_init()` expects an arena memory region supplied by the caller; `ds4_ctx_init_auto()` can optionally allocate a log ring from that arena when `cfg->log_ring_entries > 0`.

For sizing caller-provided static backing storage without duplicating overflow checks, use:

- `ds4_pool_bytes_needed(block_count,block_size,&out_bytes)`
- `ds4_ring_bytes_needed(elem_count,elem_size,&out_bytes)`

For overflow-checked allocations from arenas without repeating `count*elem_size` math, use:

- `ds4_arena_alloc_n(&arena,count,elem_size,align,&out)` and `ds4_arena_alloc_zero(&arena,size,align,&out)`
- `ds4_arena_alloc_zero_n(&arena,count,elem_size,align,&out)`
- `ds4_cuda_arena_alloc_n(&cuda_arena,count,elem_size,align,&out)` and `ds4_cuda_arena_alloc_zero(&cuda_arena,size,align,&out)`
- `ds4_cuda_arena_alloc_zero_n(&cuda_arena,count,elem_size,align,&out)`

## Logging

Logging is intentionally minimal and allocation-free:

- `include/ds4/log.h` + `src/ds4_log.c`: global log level + pluggable sink
- `include/ds4/log_ring.h` + `src/ds4_log_ring.c`: fixed-size ring capture sink (drops oldest when full; drop count via `ds4_log_ring_dropped`)

See `docs/build-logging.md`.

## Config parsing/loading

Config uses a simple `key=value` format and supports:

- Defaults (`ds4_config_defaults`)
- In-memory parsing (`ds4_config_parse_mem[_ex][_diag]`)
- File parsing/loading (`ds4_config_parse_file[_ex][_diag]`, `ds4_config_load*_ex*_diag`)
- Environment overrides (`ds4_config_parse_env`)

Diagnostics are carried via `ds4_config_diag_t` for optional 1-based line reporting on parse errors.

See `docs/build-config.md`.

## CUDA wrappers (macOS-safe)

CUDA entrypoints are wrapped behind `include/ds4/cuda.h` and compile in two modes:

- CUDA enabled: compiled from `src/ds4_cuda.cu` when `DS4_ENABLE_CUDA=ON`
- CUDA disabled: compiled from `src/ds4_cuda_stub.c` when `DS4_ENABLE_CUDA=OFF` (default on macOS)

In CPU-only builds, CUDA wrappers return `DS4_CUDA_ERR_DISABLED` while preserving link compatibility, so tests and CLI can still compile and run on macOS.

See `docs/build-cuda.md`.

## Unit tests

Tests are a single executable (`ds4_tests`) that calls per-module test functions and returns non-zero on failure.

In addition to runtime checks, the test build also compiles a small “header smoke” object library to ensure each public header in `include/ds4/*.h` is self-contained (compiles when included as the only project header in a translation unit).

CTest also includes a build-matrix smoke test (`ds4_build_matrix`) that configures/builds a few CPU-only option combinations (including a sanitizer build) to catch accidental option coupling early.

Use the Makefile wrapper on macOS:

```bash
make check BUILD_DIR=build_macos_check
```

See `docs/build.md` for the full build matrix.
