if(NOT DEFINED DS4_SOURCE_DIR)
	message(FATAL_ERROR "DS4_SOURCE_DIR is required")
endif()
if(NOT DEFINED DS4_TMP_DIR)
	message(FATAL_ERROR "DS4_TMP_DIR is required")
endif()

function(ds4_run_cmake_build name enable_tests enable_cli enable_asan enable_ubsan)
	set(_b "${DS4_TMP_DIR}/_matrix_${name}")
	file(REMOVE_RECURSE "${_b}")
	file(MAKE_DIRECTORY "${_b}")

	execute_process(
		COMMAND "${CMAKE_COMMAND}"
			-S "${DS4_SOURCE_DIR}"
			-B "${_b}"
			"-DDS4_ENABLE_TESTS=${enable_tests}"
			"-DDS4_ENABLE_CLI=${enable_cli}"
			"-DDS4_ENABLE_CUDA=OFF"
			"-DDS4_ENABLE_ASAN=${enable_asan}"
			"-DDS4_ENABLE_UBSAN=${enable_ubsan}"
			"-DDS4_WERROR=ON"
		OUTPUT_VARIABLE _cfg_out
		ERROR_VARIABLE _cfg_err
		RESULT_VARIABLE _cfg_rv
	)
	if(NOT _cfg_rv EQUAL 0)
		message(FATAL_ERROR "matrix '${name}' configure failed: ${_cfg_rv}\nstdout:\n${_cfg_out}\nstderr:\n${_cfg_err}")
	endif()

	execute_process(
		COMMAND "${CMAKE_COMMAND}" --build "${_b}" --parallel
		OUTPUT_VARIABLE _build_out
		ERROR_VARIABLE _build_err
		RESULT_VARIABLE _build_rv
	)
	if(NOT _build_rv EQUAL 0)
		message(FATAL_ERROR "matrix '${name}' build failed: ${_build_rv}\nstdout:\n${_build_out}\nstderr:\n${_build_err}")
	endif()
endfunction()

# Build-only matrix checks. Keep these CPU-only so they run on macOS and generic CI.
ds4_run_cmake_build(lib_only OFF OFF OFF OFF)
ds4_run_cmake_build(cli_only OFF ON OFF OFF)
ds4_run_cmake_build(tests_no_cli ON OFF OFF OFF)
ds4_run_cmake_build(tests_cli_sanitize ON ON ON ON)
