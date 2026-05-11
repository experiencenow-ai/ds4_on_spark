# Build Config

The build skeleton includes a minimal config parser (`ds4_config_t`) intended for static, caller-managed memory.

## File format

The parser (`ds4_config_parse_mem`, `ds4_config_parse_file`) accepts newline-delimited `key=value` pairs:

```text
# comment lines start with '#'
log_level = 2
enable_cuda = false
```

Rules:

- Blank lines are ignored.
- Leading/trailing spaces and tabs around keys/values are trimmed.
- Inline comments are supported when `#` begins a token (start-of-line or preceded by whitespace).
- Unknown keys are ignored by default.
- For strict parsing (unknown keys are errors), use `ds4_config_parse_mem_ex` / `ds4_config_parse_file_ex` with `DS4_CONFIG_PARSE_STRICT_UNKNOWN`.
- For parse diagnostics (line number + underlying parse error), use `ds4_config_parse_mem_ex_diag` / `ds4_config_parse_file_ex_diag` (and `ds4_config_load_auto_ex_diag` for the combined defaults+file+env helper). These fill a `ds4_config_diag_t` (1-based line numbers for `*_MEM`/`*_FILE` stages).
- When `out_unknown` is provided, `*_ex` functions report the unknown-key count even when strict parsing returns an error.

Supported keys:

- `log_level`: integer `0..3` (`0=ERROR`, `1=WARN`, `2=INFO`, `3=DEBUG`) or a case-insensitive name (`error`, `warn`/`warning`, `info`, `debug`)
- `enable_cuda`: boolean (`0/1`, or `true/false`, `yes/no`, `on/off`, case-insensitive)
- `cuda_device`: integer `-1` (auto / leave default device) or `>= 0` (force device index)
- `arena_size`: integer bytes (advisory; for callers that want to size arena allocations). Supports `k`/`m`/`g` suffixes (powers of 1024), e.g. `64k`, `2m`.
- `log_ring_entries`: integer entries (advisory; for callers that size log capture rings; when a `ds4_ctx_t` has a log ring initialized, `ds4_ctx_apply_config` attaches it when this value is > 0). Supports `k`/`m`/`g` suffixes, e.g. `4k`.

`ds4_config_format` prints `log_level` using the name form when the value is in-range (otherwise it falls back to the raw integer).

## C string helpers

For CLI-style overrides where keys and values are NUL-terminated strings, `ds4_config_parse_kv_cstr` computes lengths and forwards to `ds4_config_parse_kv`.

## CUDA gating

`enable_cuda` is a runtime toggle, but CUDA support is also a build-time choice:

- If DS4 is built without CUDA (`DS4_ENABLE_CUDA=OFF`), enabling CUDA via config will cause `ds4_ctx_apply_config` to fail.
- If DS4 is built with CUDA but no CUDA device is available at runtime, `ds4_ctx_apply_config` will fail (it calls `ds4_cuda_init` when `enable_cuda=1`).
- If DS4 is built with CUDA, `DS4_HAS_CUDA` is defined and `ds4_cuda_is_enabled_build()` returns `1`.

## Environment variables

You can also override config fields from the environment with `ds4_config_parse_env`:

- `DS4_LOG_LEVEL`
- `DS4_ENABLE_CUDA`
- `DS4_CUDA_DEVICE`
- `DS4_ARENA_SIZE` (supports `k`/`m`/`g` suffixes, e.g. `512k`)
- `DS4_LOG_RING_ENTRIES` (supports `k`/`m`/`g` suffixes, e.g. `4k`)

Empty or whitespace-only values (e.g. `DS4_LOG_LEVEL=""` or `DS4_LOG_LEVEL="   "`) are treated as unset and ignored; surrounding whitespace is trimmed before parsing.

`ds4_config_load_auto` also consults:

- `DS4_CONFIG_PATH` (default config file path when no `path` is provided; leading/trailing whitespace is trimmed and whitespace-only values are treated as unset)

## Load order helper

For callers that want a single entrypoint, `ds4_config_load` applies configuration in this order:

1. Defaults (`ds4_config_defaults`)
2. Optional file (`ds4_config_parse_file`) when `path` is non-empty
3. Environment overrides (`ds4_config_parse_env`)

`ds4_config_load_auto` extends this with an environment-backed config path: when `path` is empty, it uses `DS4_CONFIG_PATH` (when set) before applying env overrides.

## Static buffers

`ds4_config_parse_file` reads the config file into a caller-provided buffer:

- If the file is larger than the buffer capacity, it fails.
- This keeps the config path free of internal `malloc`.

If `path` is `"-"`, `ds4_config_parse_file` reads from `stdin` instead of opening a file.
