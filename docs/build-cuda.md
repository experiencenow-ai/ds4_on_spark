# CUDA Build Notes

DS4 wraps the CUDA Runtime API behind `include/ds4/cuda.h` so CPU-only builds can compile and run on macOS.

## Build-time toggle

- `DS4_ENABLE_CUDA=ON`: builds `src/ds4_cuda.cu`, links `CUDA::cudart`, and defines `DS4_HAS_CUDA=1`.
- `DS4_ENABLE_CUDA=OFF`: builds `src/ds4_cuda_stub.c` and `ds4_cuda_is_enabled_build()` returns `0`.

macOS defaults to `DS4_ENABLE_CUDA=OFF`.

The Makefile targets `check-cuda` / `ci-cuda` are intended for Linux runners with CUDA installed; on macOS they fail fast with a short message.

## Error wrappers

For Runtime API calls that return a CUDA error code, use:

- `DS4_CUDA_CALL(cuda_runtime_expr)`
- `DS4_CUDA_CHECK_LAST_ERROR()`
- `DS4_CUDA_CHECK_PEEK_LAST_ERROR()`

For kernel launches (or any void-returning CUDA statements compiled by NVCC), use:

- `DS4_CUDA_KERNEL_LAUNCH(kernel<<<grid,block,shared,stream>>>(...))`

`DS4_CUDA_KERNEL_LAUNCH` returns a `ds4_cuda_status_t` and logs failures with the full callsite text.

## Minimal kernel helper

For a concrete example of `DS4_CUDA_KERNEL_LAUNCH` usage, DS4 provides a tiny wrapper that fills a device buffer with a constant byte:

- `ds4_cuda_fill_u8(dst,value,bytes,stream)`

## Device allocation patterns

To avoid many small `cudaMalloc`/`cudaFree` calls in a hot path, DS4 provides a simple bump arena:

- `ds4_cuda_arena_t` (`include/ds4/cuda_arena.h`, `src/ds4_cuda_arena.c`)

## Async helpers

When sequencing copies or memset with a stream, use:

- `ds4_cuda_memset_async(dst,value,bytes,stream)`
- `ds4_cuda_memcpy_h2d_async(dst,src,bytes,stream)`
- `ds4_cuda_memcpy_d2h_async(dst,src,bytes,stream)`

## Device arena helper

For a conservative device-memory pattern, DS4 provides `ds4_cuda_arena_t` (`include/ds4/cuda_arena.h`):

- `ds4_ctx_apply_config` allocates `ctx->cuda_arena` when `enable_cuda=1` and `cuda_arena_size > 0`.
- Allocate device memory from the arena with `ds4_cuda_arena_alloc` and reset with `ds4_cuda_arena_reset`.
