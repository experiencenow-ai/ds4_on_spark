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
If the CUDA toolkit is present but no CUDA-capable device is available at runtime, `ds4_cuda_init()` returns `DS4_CUDA_ERR_NO_DEVICE` and unit tests treat that case as a soft pass.
For lightweight diagnostics, the CUDA wrapper also exposes `ds4_cuda_device_count` and `ds4_cuda_device_info` (device 0).
For host-side transfer staging, the wrapper also exposes pinned host allocation helpers `ds4_cuda_malloc_host` and `ds4_cuda_free_host` (stubbed to `DS4_CUDA_ERR_DISABLED` in CPU-only builds).

## Sanitizers (CPU-only)

Sanitizers are not supported with `DS4_ENABLE_CUDA=ON`; configuration fails if both are enabled.

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=OFF -DDS4_ENABLE_ASAN=ON -DDS4_ENABLE_UBSAN=ON
cmake --build build
ctest --test-dir build --output-on-failure
```
