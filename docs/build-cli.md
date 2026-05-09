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

Dump effective config (defaults + optional file + env):

```bash
./build_cli/ds4_cli --config path/to/ds4.conf --dump-config
```

You can also point the CLI at a default config path via `DS4_CONFIG_PATH`:

```bash
DS4_CONFIG_PATH=path/to/ds4.conf ./build_cli/ds4_cli --dump-config
```

## Tests (Smoke)

When `DS4_ENABLE_TESTS=ON` and `DS4_ENABLE_CLI=ON`, CTest includes smoke tests that run:

- `ds4_cli --version`
- `ds4_cli --dump-config`
