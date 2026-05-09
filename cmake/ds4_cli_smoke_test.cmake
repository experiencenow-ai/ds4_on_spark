if(NOT DEFINED DS4_CLI_PATH)
	message(FATAL_ERROR "DS4_CLI_PATH is required")
endif()
if(NOT DEFINED DS4_MODE)
	message(FATAL_ERROR "DS4_MODE is required")
endif()

if(DS4_MODE STREQUAL "dump_config_overrides")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --log-level debug --no-cuda --dump-config
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "log_level=debug" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'log_level=debug'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "enable_cuda=0" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'enable_cuda=0'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "version_semver")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --version
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(STRIP "${_ds4_out}" _ds4_ver)
	if(NOT _ds4_ver MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+$")
		message(FATAL_ERROR "ds4_cli --version output not semver: '${_ds4_ver}'")
	endif()
	return()
endif()

message(FATAL_ERROR "unknown DS4_MODE='${DS4_MODE}'")
