# Build

> Supersedes: `docs/build-ci.md`, `docs/build-macos.md`, `docs/build-install.md`, `docs/build-memory.md`, `docs/build-style.md`, `docs/build-skeleton.md`, `docs/build-config.md`, `docs/build-cli.md`, `docs/build-cuda.md`, `docs/build-context.md`, `docs/build.md`, `docs/build-spark.md`, `docs/build-linux.md`, `docs/build-logging.md`, `docs/build-gguf.md`

This is the canonical document for this topic. Update this file instead of adding a new overlapping note.

## Scope

- Consolidates 15 previous document(s) into one non-overlapping reference.
- Preserves stable commands, constraints, and source inventory; removes per-iteration narrative duplication.
- Historical probe/status fragments should live in git history, not as active docs.

## Current Guidance

- `build-ci.md`: Build (CI) (75 lines).
- `build-macos.md`: Build (macOS) (44 lines).
- `build-install.md`: Build (Install) (59 lines).
- `build-memory.md`: Memory Patterns (64 lines).
- `build-style.md`: Build Style (24 lines).
- `build-skeleton.md`: Build Skeleton Overview (90 lines).
- `build-config.md`: Build Config (100 lines).
- `build-cli.md`: Build (CLI) (136 lines).
- `build-cuda.md`: CUDA Build Notes (68 lines).
- `build-context.md`: Build (Context) (91 lines).
- `build.md`: Build (83 lines).
- `build-spark.md`: Spark Build (CUDA) (16 lines).
- `build-linux.md`: Build (Linux) (47 lines).
- `build-logging.md`: Build Logging (48 lines).
- `build-gguf.md`: Build (GGUF metadata-only) (27 lines).

## Command Inventory

- `build-ci.md`: `make ci BUILD_DIR=build_ci`
- `build-ci.md`: `make ci-release BUILD_DIR=build_ci_release`
- `build-ci.md`: `make ci-sanitize BUILD_DIR=build_ci_sanitize`
- `build-ci.md`: `make ci-cuda BUILD_DIR=build_ci_cuda`
- `build-macos.md`: `make build BUILD_DIR=build_macos`
- `build-macos.md`: `make test BUILD_DIR=build_macos`
- `build-macos.md`: `make check BUILD_DIR=build_macos_check`
- `build-macos.md`: `make check-sanitize BUILD_DIR=build_macos_sanitize`
- `build-macos.md`: `make check-release BUILD_DIR=build_macos_release`
- `build-install.md`: `make install BUILD_DIR=build_install PREFIX=./_install`
- `build-skeleton.md`: `make check BUILD_DIR=build_macos_check`
- `build-cli.md`: `make build BUILD_DIR=build_cli`
- `build-cli.md`: `./build_cli/ds4_cli --version`
- `build-cli.md`: `./build_cli/ds4_cli --dump-config-keys`
- `build-cli.md`: `./build_cli/ds4_cli --dump-config-help`
- `build-cli.md`: `./build_cli/ds4_cli --dump-config-template`
- `build-cli.md`: `./build_cli/ds4_cli --dump-config-env`
- `build-cli.md`: `./build_cli/ds4_cli --dump-config-env-help`
- `build-cli.md`: `./build_cli/ds4_cli --config path/to/ds4.conf --dump-config`
- `build-cli.md`: `./build_cli/ds4_cli --strict-config --config path/to/ds4.conf --dump-config`
- `build-cli.md`: `./build_cli/ds4_cli --log-level debug --cuda --cuda-device 0 --arena-size 4096 --cuda-arena-size 256m --log-ring-entries 64 --dump-config`
- `build-cli.md`: `./build_cli/ds4_cli --no-cuda --arena-size 16384 --log-ring-entries 4 --smoke-ctx`
- `build-cli.md`: `./build_cli/ds4_cli --smoke-cuda`
- `build-context.md`: `DS4_LOGI("hello from ctx");`
- `build-context.md`: `DS4_LOGI("captured into ctx ring");`
- `build-linux.md`: `make check BUILD_DIR=build_linux_cpu`
- `build-linux.md`: `make check-cuda BUILD_DIR=build_linux_cuda`
- `build-gguf.md`: `DS4_LOGI("GGUF arch: %.*s",(int)arch.len,arch.ptr);`

## Source Map

| Source | Lines | Main heading | Subsections |
|---|---:|---|---|
| `docs/build-ci.md` | 75 | Build (CI) | CPU-only (portable), CPU-only (Release), CPU-only (sanitizers), CUDA-enabled (Linux runners only) |
| `docs/build-macos.md` | 44 | Build (macOS) | Quick (Makefile), Strict warnings (Makefile), Sanitizers (Makefile, CPU-only), Release (Makefile, CPU-only), Strict warnings (CMake) |
| `docs/build-install.md` | 59 | Build (Install) | Install With A Local Prefix (Recommended), Consume From Another CMake Project, Consume With pkg-config (Optional), Makefile Wrapper, CI / Smoke Tests |
| `docs/build-memory.md` | 64 | Memory Patterns | Arena (`ds4_arena_t`), Fixed Pool (`ds4_pool_t`), Ring Buffer (`ds4_ring_t`), Log Ring (`ds4_log_ring_t`), CUDA Arena (`ds4_cuda_arena_t`) |
| `docs/build-style.md` | 24 | Build Style | C/CUDA checklist, Build hygiene |
| `docs/build-skeleton.md` | 90 | Build Skeleton Overview | Layout, Static allocation patterns, Logging, Config parsing/loading, CUDA wrappers (macOS-safe) |
| `docs/build-config.md` | 100 | Build Config | File format, Validation helper, C string helpers, CUDA gating, Environment variables |
| `docs/build-cli.md` | 136 | Build (CLI) | Build, Run, Tests (Smoke) |
| `docs/build-cuda.md` | 68 | CUDA Build Notes | Build-time toggle, Error wrappers, Minimal kernel helper, Device allocation patterns, Async helpers |
| `docs/build-context.md` | 91 | Build (Context) | Static allocation, Auto-attaching a log ring, Formatting a context snapshot, Reading captured logs, Teardown |
| `docs/build.md` | 83 | Build | Scope, Current Guidance, Command Inventory, Source Map |
| `docs/build-spark.md` | 16 | Spark Build (CUDA) | Configure and build, Notes |
| `docs/build-linux.md` | 47 | Build (Linux) | CPU-only, CUDA (requires CUDA toolkit), Sanitizers (CPU-only) |
| `docs/build-logging.md` | 48 | Build Logging | API, Default sink, Fixed-buffer sink, Ring capture, Config integration |
| `docs/build-gguf.md` | 27 | Build (GGUF metadata-only) | - |
