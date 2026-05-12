cmake_minimum_required(VERSION 3.22)

project(ds4_on_spark VERSION 0.1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

option(DS4_ENABLE_TESTS "Build unit tests" ON)
option(DS4_ENABLE_CLI "Build CLI stub" ON)
option(DS4_WERROR "Treat warnings as errors" OFF)
option(DS4_ENABLE_ASAN "Enable AddressSanitizer (CPU builds only)" OFF)
option(DS4_ENABLE_UBSAN "Enable UndefinedBehaviorSanitizer (CPU builds only)" OFF)

if(APPLE)
	set(_DS4_CUDA_DEFAULT OFF)
else()
	set(_DS4_CUDA_DEFAULT ON)
endif()
option(DS4_ENABLE_CUDA "Enable CUDA build (requires CUDA toolkit)" ${_DS4_CUDA_DEFAULT})

if(DS4_ENABLE_CUDA AND (DS4_ENABLE_ASAN OR DS4_ENABLE_UBSAN))
	message(FATAL_ERROR "Sanitizers are CPU-only; set DS4_ENABLE_CUDA=OFF or disable sanitizers")
endif()

list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

include(ds4_warnings)
include(ds4_sanitizers)
include(CheckLanguage)

add_library(ds4
	src/ds4_arena.c
	src/ds4_cuda_arena.c
	src/ds4_pool.c
	src/ds4_ring.c
	src/ds4_config.c
	src/ds4_gguf.c
	src/ds4_log.c
	src/ds4_log_ring.c
	src/ds4.c
)
add_library(ds4::ds4 ALIAS ds4)

target_include_directories(ds4
	PUBLIC
		$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
		$<INSTALL_INTERFACE:include>
)

target_compile_definitions(ds4
	PUBLIC
		DS4_VERSION_V0=${PROJECT_VERSION_MAJOR}
		DS4_VERSION_V1=${PROJECT_VERSION_MINOR}
		DS4_VERSION_V2=${PROJECT_VERSION_PATCH}
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
	target_compile_definitions(ds4 PUBLIC DS4_HAS_CUDA=0)
endif()

if(DS4_ENABLE_CLI)
	add_executable(ds4_cli
		src/ds4_cli.c
	)
	target_link_libraries(ds4_cli PRIVATE ds4)
	ds4_target_warnings(ds4_cli ${DS4_WERROR})
	ds4_target_sanitizers(ds4_cli ${DS4_ENABLE_ASAN} ${DS4_ENABLE_UBSAN})
endif()

if(DS4_ENABLE_TESTS)
	enable_testing()
	add_executable(ds4_tests
		tests/test_main.c
		tests/test_version.c
		tests/test_arena.c
		tests/test_pool.c
		tests/test_ring.c
		tests/test_config.c
		tests/test_log.c
		tests/test_ctx.c
		tests/test_cuda.c
		tests/test_cuda_arena.c
		tests/test_gguf.c
		tests/test_log_ring.c
	)
	add_library(ds4_headers_smoke OBJECT
		tests/header_smoke_arena.c
		tests/header_smoke_common.c
		tests/header_smoke_config.c
		tests/header_smoke_cuda.c
		tests/header_smoke_cuda_arena.c
		tests/header_smoke_ds4.c
		tests/header_smoke_gguf.c
		tests/header_smoke_log.c
		tests/header_smoke_log_ring.c
		tests/header_smoke_pool.c
		tests/header_smoke_ring.c
		tests/header_smoke_str.c
	)
	target_link_libraries(ds4_headers_smoke PRIVATE ds4)
	ds4_target_warnings(ds4_headers_smoke ${DS4_WERROR})
	target_sources(ds4_tests PRIVATE $<TARGET_OBJECTS:ds4_headers_smoke>)
	target_link_libraries(ds4_tests PRIVATE ds4)
	ds4_target_warnings(ds4_tests ${DS4_WERROR})
	ds4_target_sanitizers(ds4_tests ${DS4_ENABLE_ASAN} ${DS4_ENABLE_UBSAN})
	add_test(NAME ds4_tests COMMAND ds4_tests)
	if(TARGET ds4_cli)
		add_test(NAME ds4_cli_version COMMAND $<TARGET_FILE:ds4_cli> --version)
		add_test(NAME ds4_cli_dump_config COMMAND $<TARGET_FILE:ds4_cli> --dump-config)
		add_test(NAME ds4_cli_dump_config_overrides COMMAND $<TARGET_FILE:ds4_cli> --log-level debug --no-cuda --dump-config)
		add_test(NAME ds4_cli_smoke_version
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=version_semver
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_dump_config_overrides
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=dump_config_overrides
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_dump_config_keys
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=dump_config_keys
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_dump_config_help
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=dump_config_help
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_help
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=help
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_ctx
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=ctx_smoke
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_cuda_disabled
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=cuda_smoke_disabled
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_config_file_dump
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=config_file_dump
				-DDS4_TMP_DIR:PATH=${CMAKE_CURRENT_BINARY_DIR}
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_config_stdin_dump
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=config_stdin_dump
				-DDS4_TMP_DIR:PATH=${CMAKE_CURRENT_BINARY_DIR}
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_config_env_inline_dump
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=config_env_inline_dump
				-DDS4_TMP_DIR:PATH=${CMAKE_CURRENT_BINARY_DIR}
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_config_env_path_dump
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=config_env_path_dump
				-DDS4_TMP_DIR:PATH=${CMAKE_CURRENT_BINARY_DIR}
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
		add_test(NAME ds4_cli_smoke_strict_unknown_reject
			COMMAND "${CMAKE_COMMAND}"
				-DDS4_CLI_PATH=$<TARGET_FILE:ds4_cli>
				-DDS4_MODE=config_strict_unknown_reject
				-DDS4_TMP_DIR:PATH=${CMAKE_CURRENT_BINARY_DIR}
				-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_cli_smoke_test.cmake"
		)
	endif()
	add_test(NAME ds4_install_consumer
		COMMAND "${CMAKE_COMMAND}"
			-DDS4_BUILD_DIR:PATH=${CMAKE_CURRENT_BINARY_DIR}
			-DDS4_SOURCE_DIR:PATH=${CMAKE_CURRENT_SOURCE_DIR}
			-DDS4_INSTALL_PREFIX:PATH=${CMAKE_CURRENT_BINARY_DIR}/_install_test
			-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_install_consumer_test.cmake"
	)
	add_test(NAME ds4_install_consumer_cxx
		COMMAND "${CMAKE_COMMAND}"
			-DDS4_BUILD_DIR:PATH=${CMAKE_CURRENT_BINARY_DIR}
			-DDS4_SOURCE_DIR:PATH=${CMAKE_CURRENT_SOURCE_DIR}
			-DDS4_INSTALL_PREFIX:PATH=${CMAKE_CURRENT_BINARY_DIR}/_install_test_cxx
			-P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4_install_consumer_cxx_test.cmake"
	)
endif()

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

set(DS4_INSTALL_CMAKEDIR "${CMAKE_INSTALL_LIBDIR}/cmake/ds4")
if(DS4_ENABLE_CUDA)
	set(DS4_PACKAGE_HAS_CUDA 1)
else()
	set(DS4_PACKAGE_HAS_CUDA 0)
endif()

install(TARGETS ds4
	EXPORT ds4Targets
	ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
	LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
	RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
)
install(DIRECTORY include/ds4 DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")

if(TARGET ds4_cli)
	install(TARGETS ds4_cli RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
endif()

install(EXPORT ds4Targets
	NAMESPACE ds4::
	DESTINATION "${DS4_INSTALL_CMAKEDIR}"
)

configure_package_config_file(
	"${CMAKE_CURRENT_SOURCE_DIR}/cmake/ds4Config.cmake.in"
	"${CMAKE_CURRENT_BINARY_DIR}/ds4Config.cmake"
	INSTALL_DESTINATION "${DS4_INSTALL_CMAKEDIR}"
)

write_basic_package_version_file(
	"${CMAKE_CURRENT_BINARY_DIR}/ds4ConfigVersion.cmake"
	VERSION "${PROJECT_VERSION}"
	COMPATIBILITY SameMajorVersion
)

install(FILES
	"${CMAKE_CURRENT_BINARY_DIR}/ds4Config.cmake"
	"${CMAKE_CURRENT_BINARY_DIR}/ds4ConfigVersion.cmake"
	DESTINATION "${DS4_INSTALL_CMAKEDIR}"
)
