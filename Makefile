BUILD_DIR ?= build
CTEST_OPTS ?= --output-on-failure
CMAKE_OPTS ?=

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

.PHONY: all configure build test check check-cuda clean

all: build

configure:
	cmake -S . -B "$(BUILD_DIR)" -DDS4_ENABLE_TESTS="$(DS4_ENABLE_TESTS)" -DDS4_ENABLE_CLI="$(DS4_ENABLE_CLI)" -DDS4_ENABLE_CUDA="$(DS4_ENABLE_CUDA)" -DDS4_WERROR="$(DS4_WERROR)" -DDS4_ENABLE_ASAN="$(DS4_ENABLE_ASAN)" -DDS4_ENABLE_UBSAN="$(DS4_ENABLE_UBSAN)" $(CMAKE_OPTS)

build: configure
	cmake --build "$(BUILD_DIR)"

test: build
	ctest --test-dir "$(BUILD_DIR)" $(CTEST_OPTS)

check:
	$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CUDA=OFF DS4_WERROR=ON

check-cuda:
	$(MAKE) test DS4_ENABLE_TESTS=ON DS4_ENABLE_CUDA=ON DS4_WERROR=ON

clean:
	rm -rf "$(BUILD_DIR)"
