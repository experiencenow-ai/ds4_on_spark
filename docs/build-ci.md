# Build (CI)

This document describes CI-friendly command lines for CPU-only and CUDA-enabled verification.

The default CI posture should be CPU-only (`DS4_ENABLE_CUDA=OFF`) so it can run on macOS and generic Linux runners.

## CPU-only (portable)

Makefile wrapper (recommended):

```bash
make ci BUILD_DIR=build_ci
```

Equivalent CMake commands:

```bash
cmake -S . -B build_ci -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CLI=ON -DDS4_ENABLE_CUDA=OFF -DDS4_WERROR=ON
cmake --build build_ci
ctest --test-dir build_ci --output-on-failure
```

## CPU-only (Release)

Some bugs only reproduce with optimizations enabled. For an optimized CPU-only run:

Makefile wrapper:

```bash
make ci-release BUILD_DIR=build_ci_release
```

Equivalent CMake commands:

```bash
cmake -S . -B build_ci_release -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CLI=ON -DDS4_ENABLE_CUDA=OFF -DDS4_WERROR=ON -DCMAKE_BUILD_TYPE=Release
cmake --build build_ci_release
ctest --test-dir build_ci_release --output-on-failure
```

## CPU-only (sanitizers)

Sanitizers are CPU-only (configuration fails if `DS4_ENABLE_CUDA=ON`).

Makefile wrapper:

```bash
make ci-sanitize BUILD_DIR=build_ci_sanitize
```

Equivalent CMake commands:

```bash
cmake -S . -B build_ci_asan -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CLI=ON -DDS4_ENABLE_CUDA=OFF -DDS4_ENABLE_ASAN=ON -DDS4_ENABLE_UBSAN=ON -DDS4_WERROR=ON
cmake --build build_ci_asan
ctest --test-dir build_ci_asan --output-on-failure
```

## CUDA-enabled (Linux runners only)

Makefile wrapper:

```bash
make ci-cuda BUILD_DIR=build_ci_cuda
```

Equivalent CMake commands:

```bash
cmake -S . -B build_ci_cuda -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CLI=ON -DDS4_ENABLE_CUDA=ON -DDS4_WERROR=ON
cmake --build build_ci_cuda
ctest --test-dir build_ci_cuda --output-on-failure
```
