# Build (Context)

The build skeleton includes a conservative context handle, `ds4_ctx_t`, intended to group:

- A copy of the effective config (`ds4_config_t`)
- A caller-provided arena (`ds4_arena_t`)
- An optional caller-provided log capture ring (`ds4_log_ring_t`)
- An optional CUDA device bump arena (`ds4_cuda_arena_t`) when `enable_cuda=1` and `cuda_arena_size > 0`

## Static allocation

`ds4_ctx_t` does not allocate from the host heap. Callers supply fixed buffers up front:

- CPU arena memory is always caller-provided.
- CUDA device memory is optional and only allocated when `enable_cuda=1` and `cuda_arena_size > 0` (via `cudaMalloc`).

```c
#include "ds4/ds4.h"

static uint8_t g_arena_mem[1<<20];
static ds4_log_entry_t g_log_entries[256];

int32_t example(void)
{
	ds4_ctx_t ctx;
	ds4_config_t cfg;
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	if ( ds4_ctx_init(&ctx,&cfg,g_arena_mem,(int32_t)sizeof(g_arena_mem)) < 0 )
		return(-2);
	if ( ds4_ctx_log_ring_init(&ctx,g_log_entries,(int32_t)(sizeof(g_log_entries) / sizeof(g_log_entries[0]))) < 0 )
		return(-3);
	cfg.log_ring_entries = (int32_t)(sizeof(g_log_entries) / sizeof(g_log_entries[0]));
	if ( ds4_ctx_apply_config(&ctx,&cfg) < 0 )
		return(-4);
	DS4_LOGI("hello from ctx");
	return(0);
}
```

Notes:

- `ds4_ctx_init` applies config immediately, so to enable log capture you typically initialize the ring and then call `ds4_ctx_apply_config` once more with `log_ring_entries > 0`.
- Logging is currently process-global (`ds4_log_set_sink`); wiring a ring into one context affects all `DS4_LOG*` calls in the process.

## Auto-attaching a log ring

To avoid a two-phase init, `ds4_ctx_init_auto` can allocate the log ring entries out of the arena (static caller-provided buffer) and attach capture in the same call:

```c
#include "ds4/ds4.h"

static uint8_t g_arena_mem[1<<20];

int32_t example_auto(void)
{
	ds4_ctx_t ctx;
	ds4_config_t cfg;
	if ( ds4_config_defaults(&cfg) < 0 )
		return(-1);
	cfg.log_ring_entries = 256;
	if ( ds4_ctx_init_auto(&ctx,&cfg,g_arena_mem,(int32_t)sizeof(g_arena_mem)) < 0 )
		return(-2);
	DS4_LOGI("captured into ctx ring");
	return(0);
}
```

To help size the host arena for `ds4_ctx_init_auto`, `ds4_ctx_auto_arena_bytes` computes the minimum number of arena bytes needed for the auto-managed allocations implied by a config (currently: the log ring entries when `log_ring_entries > 0`).

## Formatting a context snapshot

For allocation-free diagnostics (for logs or CLI output), `ds4_ctx_format` formats the effective config plus a small ctx state snapshot (arena usage, log ring state, CUDA arena state) into a caller-provided buffer.

## Reading captured logs

After you attach a log ring, you can retrieve entries via:

- `ds4_ctx_log_ring_count`
- `ds4_ctx_log_ring_pop`

To disable ctx-managed capture, set `cfg.log_ring_entries = 0` and call `ds4_ctx_apply_config` (it detaches the sink only if the context previously attached it).

## Teardown

Logging is currently process-global (`ds4_log_set_sink`), so if a context attached a log ring you should detach before the ring storage goes out of scope.

Use either:

- `ds4_ctx_log_ring_detach` (detach only)
- `ds4_ctx_deinit` (detach and clear ctx log-ring state)
