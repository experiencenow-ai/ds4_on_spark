# Build (macOS)

This project defaults to `DS4_ENABLE_CUDA=OFF` on macOS.

## Quick (Makefile)

```bash
make clean
make build
make test
```

## Strict warnings (Makefile)

```bash
make clean
make check
```

## Strict warnings (CMake)

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=OFF -DDS4_WERROR=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

## Sanitizers (CPU-only)

```bash
cmake -S . -B build -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CUDA=OFF -DDS4_ENABLE_ASAN=ON -DDS4_ENABLE_UBSAN=ON
cmake --build build
ctest --test-dir build --output-on-failure
```
