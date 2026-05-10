# CUDA Build Notes

DS4 wraps the CUDA Runtime API behind `include/ds4/cuda.h` so CPU-only builds can compile and run on macOS.

## Build-time toggle

- `DS4_ENABLE_CUDA=ON`: builds `src/ds4_cuda.cu`, links `CUDA::cudart`, and defines `DS4_HAS_CUDA=1`.
- `DS4_ENABLE_CUDA=OFF`: builds `src/ds4_cuda_stub.c` and `ds4_cuda_is_enabled_build()` returns `0`.

macOS defaults to `DS4_ENABLE_CUDA=OFF`.

## Error wrappers

For Runtime API calls that return a CUDA error code, use:

- `DS4_CUDA_CALL(cuda_runtime_expr)`
- `DS4_CUDA_CHECK_LAST_ERROR()`
- `DS4_CUDA_CHECK_PEEK_LAST_ERROR()`

For kernel launches (or any void-returning CUDA statements compiled by NVCC), use:

- `DS4_CUDA_KERNEL_LAUNCH(kernel<<<grid,block,shared,stream>>>(...))`

`DS4_CUDA_KERNEL_LAUNCH` returns a `ds4_cuda_status_t` and logs failures with the full callsite text.
