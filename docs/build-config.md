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

Supported keys:

- `log_level`: integer `0..3` (`0=ERROR`, `1=WARN`, `2=INFO`, `3=DEBUG`)
- `enable_cuda`: boolean (`0/1`, or `true/false`, `yes/no`, `on/off`, case-insensitive)

## CUDA gating

`enable_cuda` is a runtime toggle, but CUDA support is also a build-time choice:

- If DS4 is built without CUDA (`DS4_ENABLE_CUDA=OFF`), enabling CUDA via config will cause `ds4_ctx_apply_config` to fail.
- If DS4 is built with CUDA, `DS4_HAS_CUDA` is defined and `ds4_cuda_is_enabled_build()` returns `1`.

## Environment variables

You can also override config fields from the environment with `ds4_config_parse_env`:

- `DS4_LOG_LEVEL`
- `DS4_ENABLE_CUDA`

`ds4_config_load_auto` also consults:

- `DS4_CONFIG_PATH` (default config file path when no `path` is provided)

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
