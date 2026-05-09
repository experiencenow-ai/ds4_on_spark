# Build (Linux)

Linux builds can be CPU-only or CUDA-enabled.

## CPU-only

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=OFF
cmake --build build
ctest --test-dir build --output-on-failure
```

Or via the Makefile wrapper:

```bash
make check BUILD_DIR=build_linux_cpu
```

## CUDA (requires CUDA toolkit)

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Or via the Makefile wrapper:

```bash
make check-cuda BUILD_DIR=build_linux_cuda
```

If CUDA is not available, configuration fails with an explicit error when `DS4_ENABLE_CUDA=ON`.

## Sanitizers (CPU-only)

Sanitizers are not supported with `DS4_ENABLE_CUDA=ON`; configuration fails if both are enabled.

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=OFF -DDS4_ENABLE_ASAN=ON -DDS4_ENABLE_UBSAN=ON
cmake --build build
ctest --test-dir build --output-on-failure
```
