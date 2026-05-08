# Build

This repo uses CMake and ships a thin `Makefile` wrapper.

See also:

- `docs/build-macos.md`
- `docs/build-linux.md`

## Mac (no CUDA)

```bash
make clean
make build
make test
```

## Linux (optional CUDA)

To enable CUDA, configure with:

```bash
cmake -S . -B build -DDS4_ENABLE_CUDA=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

`DS4_ENABLE_CUDA` is `OFF` by default on macOS.
