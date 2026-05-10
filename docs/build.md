# Build

This repo uses CMake and ships a thin `Makefile` wrapper.

See also:

- `docs/build-ci.md`
- `docs/build-macos.md`
- `docs/build-linux.md`
- `docs/build-spark.md`
- `docs/build-style.md`
- `docs/build-memory.md`
- `docs/build-config.md`
- `docs/build-cli.md`
- `docs/build-logging.md`
- `docs/build-context.md`
- `docs/build-install.md`
- `docs/build-gguf.md`

## Mac (no CUDA)

```bash
make build BUILD_DIR=build_macos
make test BUILD_DIR=build_macos
```

For a portable, CPU-only strict build (warnings-as-errors), use:

```bash
make check BUILD_DIR=build_macos_check
```

## Linux (optional CUDA)

To enable CUDA, configure with:

```bash
cmake -S . -B build -DDS4_ENABLE_CUDA=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

`DS4_ENABLE_CUDA` is `OFF` by default on macOS.
Sanitizers are CPU-only; configuration fails if `DS4_ENABLE_CUDA=ON` with `DS4_ENABLE_ASAN`/`DS4_ENABLE_UBSAN`.
