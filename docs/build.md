# Build

This repo uses CMake and ships a thin `Makefile` wrapper.

See also:

- `docs/build-macos.md`
- `docs/build-linux.md`
- `docs/build-spark.md`
- `docs/build-memory.md`
- `docs/build-config.md`
- `docs/build-cli.md`

## Mac (no CUDA)

```bash
make clean
make build
make test
```

For a portable, CPU-only strict build (warnings-as-errors), use:

```bash
make clean
make check
```

## Linux (optional CUDA)

To enable CUDA, configure with:

```bash
cmake -S . -B build -DDS4_ENABLE_CUDA=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

`DS4_ENABLE_CUDA` is `OFF` by default on macOS.
