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
make clean
make check
```

## CUDA (requires CUDA toolkit)

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Or via the Makefile wrapper:

```bash
make clean
make check-cuda
```

If CUDA is not available, configuration fails with an explicit error when `DS4_ENABLE_CUDA=ON`.

## Sanitizers (CPU-only)

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=OFF -DDS4_ENABLE_ASAN=ON -DDS4_ENABLE_UBSAN=ON
cmake --build build
ctest --test-dir build --output-on-failure
```
