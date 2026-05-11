BUILD_DIR ?= build
CTEST_OPTS ?= --output-on-failure
CMAKE_OPTS ?=
BUILD_TYPE ?=
PREFIX ?=
INSTALL_OPTS ?=

UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
DS4_ENABLE_CUDA ?= OFF
else
DS4_ENABLE_CUDA ?= ON
endif
DS4_ENABLE_TESTS ?= ON
DS4_ENABLE_CLI ?= ON
DS4_WERROR ?= OFF
DS4_ENABLE_ASAN ?= OFF
DS4_ENABLE_UBSAN ?= OFF

ifneq ($(BUILD_TYPE),)
DS4_CMAKE_BUILD_TYPE_OPT := -DCMAKE_BUILD_TYPE="$(BUILD_TYPE)"
else
DS4_CMAKE_BUILD_TYPE_OPT :=
endif

.PHONY: all configure build test check check-cuda check-asan check-ubsan check-sanitize check-release ci ci-cuda ci-sanitize ci-release install clean

all: build

configure:
	cmake -S . -B "$(BUILD_DIR)" -DDS4_ENABLE_TESTS="$(DS4_ENABLE_TESTS)" -DDS4_ENABLE_CLI="$(DS4_ENABLE_CLI)" -DDS4_ENABLE_CUDA="$(DS4_ENABLE_CUDA)" -DDS4_WERROR="$(DS4_WERROR)" -DDS4_ENABLE_ASAN="$(DS4_ENABLE_ASAN)" -DDS4_ENABLE_UBSAN="$(DS4_ENABLE_UBSAN)" $(DS4_CMAKE_BUILD_TYPE_OPT) $(CMAKE_OPTS)

build: configure
	env MAKEFLAGS= cmake --build "$(BUILD_DIR)" --parallel

test: build
	ctest --test-dir "$(BUILD_DIR)" $(CTEST_OPTS)

check:
	+$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CLI=ON DS4_ENABLE_CUDA=OFF DS4_WERROR=ON

check-cuda:
	@if [ "$(UNAME_S)" = "Darwin" ]; then echo "check-cuda: unsupported on macOS (run on Linux with CUDA toolkit)"; exit 2; fi
	+$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CLI=ON DS4_ENABLE_CUDA=ON DS4_WERROR=ON

check-asan:
	+$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CLI=ON DS4_ENABLE_CUDA=OFF DS4_WERROR=ON DS4_ENABLE_ASAN=ON DS4_ENABLE_UBSAN=OFF

check-ubsan:
	+$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CLI=ON DS4_ENABLE_CUDA=OFF DS4_WERROR=ON DS4_ENABLE_ASAN=OFF DS4_ENABLE_UBSAN=ON

check-sanitize:
	+$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CLI=ON DS4_ENABLE_CUDA=OFF DS4_WERROR=ON DS4_ENABLE_ASAN=ON DS4_ENABLE_UBSAN=ON

check-release:
	+$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CLI=ON DS4_ENABLE_CUDA=OFF DS4_WERROR=ON BUILD_TYPE=Release

ci: check

ci-cuda: check-cuda

ci-sanitize: check-sanitize

ci-release: check-release

install: build
	@if [ -n "$(PREFIX)" ]; then cmake --install "$(BUILD_DIR)" --prefix "$(PREFIX)" $(INSTALL_OPTS); else cmake --install "$(BUILD_DIR)" $(INSTALL_OPTS); fi

clean:
	@if [ -z "$(BUILD_DIR)" ] || [ "$(BUILD_DIR)" = "/" ] || [ "$(BUILD_DIR)" = "." ]; then echo "Refusing to remove BUILD_DIR='$(BUILD_DIR)'"; exit 2; fi
	rm -rf "$(BUILD_DIR)"
