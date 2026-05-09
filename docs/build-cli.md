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
