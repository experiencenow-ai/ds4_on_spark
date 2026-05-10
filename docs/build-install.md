# Build (Install)

The build skeleton provides CMake install rules for the `ds4` static library, public headers, and (optionally) the `ds4_cli` binary.

## Install With A Local Prefix (Recommended)

```bash
cmake -S . -B build_install -DDS4_ENABLE_CLI=ON
cmake --build build_install
cmake --install build_install --prefix ./_install
```

This installs:

- `libds4.a` under `./_install/lib` (platform-dependent subdir via `GNUInstallDirs`)
- headers under `./_install/include/ds4`
- `ds4_cli` under `./_install/bin` (when built)
- CMake package files under `./_install/lib/cmake/ds4`

## Consume From Another CMake Project

With `CMAKE_PREFIX_PATH` pointed at the install prefix:

```bash
cmake -S . -B build_consumer -DCMAKE_PREFIX_PATH=/path/to/ds4/_install
```

Then in the consumer `CMakeLists.txt`:

```cmake
find_package(ds4 CONFIG REQUIRED)
target_link_libraries(my_target PRIVATE ds4::ds4)
```

## Makefile Wrapper

```bash
make install BUILD_DIR=build_install PREFIX=./_install
```

## CI / Smoke Tests

When `DS4_ENABLE_TESTS=ON`, `ctest` runs two install-consumer smoke tests:

- `ds4_install_consumer`: installs the build and compiles a small C consumer.
- `ds4_install_consumer_cxx`: installs the build and compiles a small C++ consumer.

Both consumers include all public `ds4/*.h` headers to catch missing includes and C++ compatibility regressions early.
