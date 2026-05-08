BUILD_DIR ?= build
CTEST_OPTS ?= --output-on-failure

.PHONY: all configure build test clean

all: build

configure:
	cmake -S . -B "$(BUILD_DIR)" -DDS4_ENABLE_TESTS=ON

build: configure
	cmake --build "$(BUILD_DIR)"

test: build
	ctest --test-dir "$(BUILD_DIR)" $(CTEST_OPTS)

clean:
	rm -rf "$(BUILD_DIR)"
