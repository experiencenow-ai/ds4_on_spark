# Build (macOS)

This project defaults to `DS4_ENABLE_CUDA=OFF` on macOS.

## Quick (Makefile)

```bash
make build BUILD_DIR=build_macos
make test BUILD_DIR=build_macos
```

## Strict warnings (Makefile)

```bash
make check BUILD_DIR=build_macos_check
```

## Sanitizers (Makefile, CPU-only)

```bash
make check-sanitize BUILD_DIR=build_macos_sanitize
```

## Release (Makefile, CPU-only)

```bash
make check-release BUILD_DIR=build_macos_release
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
