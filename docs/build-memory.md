# Memory Patterns

The build skeleton aims for predictable, static allocation. Most call sites should avoid `malloc`/`free` and instead use caller-provided buffers.

## Arena (`ds4_arena_t`)

`ds4_arena_t` is a bump allocator over a caller-provided memory region:

- `ds4_arena_alloc`: allocates aligned slices (no free).
- `ds4_arena_alloc_n`: `count*elem_size` allocation with overflow checks (useful for arrays).
- `ds4_arena_alloc_zero`: allocates and zero-fills the returned region.
- `ds4_arena_alloc_zero_n`: `count*elem_size` array allocation with overflow checks and zero-fill.
- `ds4_arena_mark` / `ds4_arena_release`: coarse rollback to a prior mark.
- `ds4_arena_reset`: discard all allocations.
- `ds4_arena_validate`: basic sanity checks for diagnostics/debug.
- `ds4_arena_bytes_left`: remaining capacity helper (no allocation).

Typical usage: allocate per-request scratch memory, or build fixed-size graphs without per-node `malloc`.

Alignment note: `ds4_arena_alloc` aligns relative to the arena base pointer, so callers should provide aligned arena storage (e.g. `_Alignas(16) uint8_t arena_mem[...]`). For defensive checks, `ds4_arena_init_ex(...,16)` rejects misaligned bases.

## Fixed Pool (`ds4_pool_t`)

`ds4_pool_t` is a fixed-block allocator backed by a caller-provided memory region:

- `ds4_pool_init`: partitions memory into equal-sized blocks.
- `ds4_pool_alloc`: returns one block.
- `ds4_pool_alloc_zero`: returns one block and zero-fills it.
- `ds4_pool_free`: returns a block to the pool.

This pattern is useful when you know the max number of same-sized objects ahead of time (e.g. queue nodes, small structs).

Notes:

- The pool does not currently detect double-free; keep ownership disciplined at call sites.
- The pool stores its free list inside the blocks themselves; a freed block’s first 4 bytes are used for internal bookkeeping.

## Ring Buffer (`ds4_ring_t`)

`ds4_ring_t` is a fixed-size ring queue backed by caller-provided memory:

- `ds4_ring_push` / `ds4_ring_pop`: push/pop fixed-size elements by copying.
- Useful for bounded event queues, message passing between components, or simple telemetry buffers.

## Log Ring (`ds4_log_ring_t`)

`ds4_log_ring_t` is a simple fixed-size log capture sink built on `ds4_ring_t`:

- Initialize with caller-provided `ds4_log_entry_t` storage.
- Wire into the logger with `ds4_log_set_sink(ds4_log_ring_sink,&ring)`.
- When full, it evicts the oldest entry and keeps the newest.

When using `ds4_ctx_t`, you can allocate the log ring backing store from the ctx arena (still caller-owned memory) via `ds4_ctx_log_ring_init_arena`.

## CUDA Arena (`ds4_cuda_arena_t`)

When built with CUDA, `ds4_cuda_arena_t` is a bump allocator over a single `cudaMalloc` region:

- `ds4_cuda_arena_alloc`: allocates aligned device slices (no free).
- `ds4_cuda_arena_alloc_n`: `count*elem_size` allocation with overflow checks.
- `ds4_cuda_arena_alloc_zero`: allocates and zero-fills via `cudaMemset` (returns `DS4_CUDA_ERR_DISABLED` in CPU-only builds).
- `ds4_cuda_arena_alloc_zero_n`: `count*elem_size` array allocation with overflow checks and zero-fill (returns `DS4_CUDA_ERR_DISABLED` in CPU-only builds).
- `ds4_cuda_arena_reset`: discard all allocations.
