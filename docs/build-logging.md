# Build Logging

The build skeleton includes a minimal logging facility (`ds4/log.h`) that avoids heap allocation and supports pluggable sinks.

## API

- `ds4_log_set_level(level)`: Sets the global log level (`0..3`).
- `ds4_log_set_sink(fn,ctx)`: Installs a sink callback and its context pointer.
- `ds4_logf(level,fmt,...)`: Formats a message into a fixed stack buffer and dispatches it to the active sink.

Convenience macros:

- `DS4_LOGE(...)`, `DS4_LOGW(...)`, `DS4_LOGI(...)`, `DS4_LOGD(...)`

## Default sink

When no sink is installed, DS4 logs to `stderr` as:

```text
level: message
```

## Fixed-buffer sink

For tests or in-memory capture, use `ds4_log_buf_t`:

- `ds4_log_buf_init(&lb,buf,cap)`: Initializes a caller-provided buffer.
- `ds4_log_buf_sink`: Appends `message\n` to the buffer.
- `ds4_log_buf_sink_prefixed`: Appends `level: message\n` to the buffer.

Both buffer sinks set `lb.truncated=1` if the buffer fills (while keeping it NUL-terminated).

## Ring capture

For fixed-size log capture with per-entry metadata, `ds4/log_ring.h` provides:

- `ds4_log_ring_sink`: Captures `{level,truncated,msg[]}` entries into a caller-provided ring.
- `ds4_log_ring_pop`: Pops the oldest entry.
- `ds4_log_entry_format`: Formats a popped `ds4_log_entry_t` as `level: msg` (appends ` [truncated]` when the entry was truncated).

This is intended for embedded-style “keep the last N events” debugging without allocations.

## Config integration

`ds4_ctx_apply_config` applies `cfg->log_level` via `ds4_log_set_level`, so callers that initialize `ds4_ctx_t` automatically get the configured logging level.
