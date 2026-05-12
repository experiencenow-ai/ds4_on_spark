# Build (CLI)

The build skeleton includes a small CLI stub target, `ds4_cli`, intended for smoke-testing config parsing and logging behavior.

## Build

```bash
cmake -S . -B build -DDS4_ENABLE_CLI=ON
cmake --build build
```

Or via the Makefile wrapper:

```bash
make build BUILD_DIR=build_cli
```

## Run

Print the version:

```bash
./build_cli/ds4_cli --version
```

Print supported config keys:

```bash
./build_cli/ds4_cli --dump-config-keys
```

Dump effective config (defaults + optional file + env):

```bash
./build_cli/ds4_cli --config path/to/ds4.conf --dump-config
```

Read config from stdin:

```bash
cat path/to/ds4.conf | ./build_cli/ds4_cli --config - --dump-config
```

Reject unknown keys in the config file:

```bash
./build_cli/ds4_cli --strict-config --config path/to/ds4.conf --dump-config
```

When strict parsing fails due to unknown keys, `ds4_cli` reports how many were seen.

Override config fields from the command line:

```bash
./build_cli/ds4_cli --log-level debug --cuda --cuda-device 0 --arena-size 4096 --cuda-arena-size 256m --log-ring-entries 64 --dump-config
```

Smoke-test ctx init and log-ring capture (static arena, one log line):

```bash
./build_cli/ds4_cli --no-cuda --arena-size 16384 --log-ring-entries 4 --smoke-ctx
```

Expected stdout includes:

```
log_ring: ds4_cli smoke ctx
```

Smoke-test CUDA wrapper status (prints build support and config state):

```bash
./build_cli/ds4_cli --smoke-cuda
```

On Linux builds with CUDA enabled, you can also probe a device by setting `enable_cuda=1`:

```bash
./build_cli/ds4_cli --cuda --smoke-cuda
```

You can also point the CLI at a default config path via `DS4_CONFIG_PATH`:

```bash
DS4_CONFIG_PATH=path/to/ds4.conf ./build_cli/ds4_cli --dump-config
```

You can also supply inline config text (newline-delimited `key=value` pairs) via `DS4_CONFIG`:

```bash
DS4_CONFIG="log_level=debug" ./build_cli/ds4_cli --dump-config
```

## Tests (Smoke)

When `DS4_ENABLE_TESTS=ON` and `DS4_ENABLE_CLI=ON`, CTest includes smoke tests that run:

- `ds4_cli --version`
- `ds4_cli --dump-config`
- `ds4_cli --dump-config-keys`
- `ds4_cli --smoke-cuda`
- `ds4_cli --config <tmpfile> --dump-config`
- `ds4_cli --config - --dump-config` (stdin)
- `DS4_CONFIG=... ds4_cli --dump-config`
- `DS4_CONFIG_PATH=... ds4_cli --dump-config`
