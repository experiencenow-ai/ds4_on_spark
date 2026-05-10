if(NOT DEFINED DS4_BUILD_DIR)
	message(FATAL_ERROR "DS4_BUILD_DIR is required")
endif()
if(NOT DEFINED DS4_SOURCE_DIR)
	message(FATAL_ERROR "DS4_SOURCE_DIR is required")
endif()
if(NOT DEFINED DS4_INSTALL_PREFIX)
	message(FATAL_ERROR "DS4_INSTALL_PREFIX is required")
endif()

file(REMOVE_RECURSE "${DS4_INSTALL_PREFIX}")
file(MAKE_DIRECTORY "${DS4_INSTALL_PREFIX}")

execute_process(
	COMMAND "${CMAKE_COMMAND}" --install "${DS4_BUILD_DIR}" --prefix "${DS4_INSTALL_PREFIX}"
	RESULT_VARIABLE _ds4_install_rv
)
if(NOT _ds4_install_rv EQUAL 0)
	message(FATAL_ERROR "cmake --install failed: ${_ds4_install_rv}")
endif()

set(_ds4_consumer_src "${DS4_BUILD_DIR}/_consumer_src")
set(_ds4_consumer_build "${DS4_BUILD_DIR}/_consumer_build")
file(REMOVE_RECURSE "${_ds4_consumer_src}" "${_ds4_consumer_build}")
file(MAKE_DIRECTORY "${_ds4_consumer_src}")

file(WRITE "${_ds4_consumer_src}/CMakeLists.txt" "cmake_minimum_required(VERSION 3.24)\nproject(ds4_consumer LANGUAGES C)\nfind_package(ds4 CONFIG REQUIRED)\nget_target_property(DS4_DEFS ds4::ds4 INTERFACE_COMPILE_DEFINITIONS)\nget_target_property(DS4_LINK ds4::ds4 INTERFACE_LINK_LIBRARIES)\nif(NOT DS4_DEFS MATCHES \"(^|;)DS4_HAS_CUDA=[01](;|$)\")\n\tmessage(FATAL_ERROR \"ds4::ds4 must export DS4_HAS_CUDA=0 or DS4_HAS_CUDA=1\")\nendif()\nif(DS4_DEFS MATCHES \"(^|;)DS4_HAS_CUDA=1(;|$)\")\n\tif(NOT DS4_LINK MATCHES \"(^|;)CUDA::cudart(;|$)\")\n\t\tmessage(FATAL_ERROR \"ds4::ds4 exports DS4_HAS_CUDA=1 but does not link CUDA::cudart\")\n\tendif()\nendif()\nadd_executable(ds4_consumer main.c)\ntarget_link_libraries(ds4_consumer PRIVATE ds4::ds4)\n")

file(WRITE "${_ds4_consumer_src}/main.c" "#include <stdint.h>\n\n#include <ds4/common.h>\n#include <ds4/arena.h>\n#include <ds4/pool.h>\n#include <ds4/ring.h>\n#include <ds4/config.h>\n#include <ds4/gguf.h>\n#include <ds4/log.h>\n#include <ds4/log_ring.h>\n#include <ds4/cuda.h>\n#include <ds4/ds4.h>\n\nint main(void)\n{\n\tds4_ctx_t ctx;\n\tds4_config_t cfg;\n\tuint8_t arena[1024];\n\tif ( ds4_config_defaults(&cfg) < 0 )\n\t\treturn(1);\n\tif ( ds4_ctx_init(&ctx,&cfg,arena,(int32_t)sizeof(arena)) < 0 )\n\t\treturn(2);\n\treturn(0);\n}\n")

set(_ds4_pkgdir "${DS4_INSTALL_PREFIX}/lib/cmake/ds4")
message(STATUS "ds4_consumer_test: prefix='${DS4_INSTALL_PREFIX}' pkgdir='${_ds4_pkgdir}'")

execute_process(
	COMMAND "${CMAKE_COMMAND}"
		-S "${_ds4_consumer_src}"
		-B "${_ds4_consumer_build}"
		"-DCMAKE_PREFIX_PATH=${DS4_INSTALL_PREFIX}"
		"-Dds4_DIR=${_ds4_pkgdir}"
	OUTPUT_VARIABLE _ds4_config_out
	ERROR_VARIABLE _ds4_config_err
	RESULT_VARIABLE _ds4_config_rv
)
if(NOT _ds4_config_rv EQUAL 0)
	message(FATAL_ERROR "consumer configure failed: ${_ds4_config_rv}\nstdout:\n${_ds4_config_out}\nstderr:\n${_ds4_config_err}")
endif()

execute_process(
	COMMAND "${CMAKE_COMMAND}" --build "${_ds4_consumer_build}"
	RESULT_VARIABLE _ds4_build_rv
)
if(NOT _ds4_build_rv EQUAL 0)
	message(FATAL_ERROR "consumer build failed: ${_ds4_build_rv}")
endif()
