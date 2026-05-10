# Spark Build (CUDA)

This repo’s build skeleton supports an optional CUDA build when the CUDA toolkit is available.

## Configure and build

```bash
cmake -S . -B build_spark -DDS4_ENABLE_TESTS=ON -DDS4_ENABLE_CLI=ON -DDS4_ENABLE_CUDA=ON -DDS4_WERROR=ON
cmake --build build_spark
ctest --test-dir build_spark --output-on-failure
```

## Notes

- `DS4_ENABLE_CUDA=ON` requires a working CUDA toolkit (`FindCUDAToolkit`).
- The default for `DS4_ENABLE_CUDA` is `OFF` on macOS and `ON` on Linux.
