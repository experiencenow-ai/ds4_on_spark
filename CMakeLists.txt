cmake_minimum_required(VERSION 3.24)

project(ds4_on_spark LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

option(DS4_ENABLE_TESTS "Build unit tests" ON)
option(DS4_WERROR "Treat warnings as errors" OFF)
option(DS4_ENABLE_ASAN "Enable AddressSanitizer (CPU builds only)" OFF)
option(DS4_ENABLE_UBSAN "Enable UndefinedBehaviorSanitizer (CPU builds only)" OFF)

if(APPLE)
	set(_DS4_CUDA_DEFAULT OFF)
else()
	set(_DS4_CUDA_DEFAULT ON)
endif()
option(DS4_ENABLE_CUDA "Enable CUDA build (requires CUDA toolkit)" ${_DS4_CUDA_DEFAULT})

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

include(ds4_warnings)
include(ds4_sanitizers)
include(CheckLanguage)

add_library(ds4
	src/ds4_arena.c
	src/ds4_config.c
	src/ds4_log.c
	src/ds4.c
)

target_include_directories(ds4
	PUBLIC
		"${CMAKE_CURRENT_SOURCE_DIR}/include"
)

ds4_target_warnings(ds4 ${DS4_WERROR})
ds4_target_sanitizers(ds4 ${DS4_ENABLE_ASAN} ${DS4_ENABLE_UBSAN})

if(DS4_ENABLE_CUDA)
	check_language(CUDA)
	if(NOT CMAKE_CUDA_COMPILER)
		message(FATAL_ERROR "DS4_ENABLE_CUDA=ON but CUDA language is unavailable")
	endif()
	enable_language(CUDA)
	include(ds4_cuda)
	ds4_target_cuda(ds4)
else()
	target_sources(ds4 PRIVATE src/ds4_cuda_stub.c)
endif()

if(DS4_ENABLE_TESTS)
	enable_testing()
	add_executable(ds4_tests
		tests/test_main.c
		tests/test_arena.c
		tests/test_config.c
		tests/test_log.c
		tests/test_ctx.c
		tests/test_cuda.c
	)
	target_link_libraries(ds4_tests PRIVATE ds4)
	ds4_target_warnings(ds4_tests ${DS4_WERROR})
	ds4_target_sanitizers(ds4_tests ${DS4_ENABLE_ASAN} ${DS4_ENABLE_UBSAN})
	add_test(NAME ds4_tests COMMAND ds4_tests)
endif()
