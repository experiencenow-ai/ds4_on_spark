if(NOT DEFINED DS4_CLI_PATH)
	message(FATAL_ERROR "DS4_CLI_PATH is required")
endif()
if(NOT DEFINED DS4_MODE)
	message(FATAL_ERROR "DS4_MODE is required")
endif()

if(DS4_MODE MATCHES "^config_")
	if(NOT DEFINED DS4_TMP_DIR)
		message(FATAL_ERROR "DS4_TMP_DIR is required for DS4_MODE='${DS4_MODE}'")
	endif()
endif()

if(DS4_MODE STREQUAL "dump_config_overrides")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --log-level debug --no-cuda --arena-size 4096 --log-ring-entries 64 --dump-config
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
	string(FIND "${_ds4_out}" "arena_size=4096" _ds4_idx3)
	if(_ds4_idx3 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'arena_size=4096'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "log_ring_entries=64" _ds4_idx4)
	if(_ds4_idx4 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'log_ring_entries=64'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "dump_config_keys")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --dump-config-keys
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "log_level" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'log_level'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "enable_cuda" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'enable_cuda'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "dump_config_help")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --dump-config-help
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "log_level:" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'log_level:'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "enable_cuda:" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'enable_cuda:'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "dump_config_template")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --dump-config-template
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "# log_level:" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing '# log_level:'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "log_level=" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'log_level='\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "enable_cuda=" _ds4_idx3)
	if(_ds4_idx3 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'enable_cuda='\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "dump_config_env")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --dump-config-env
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "DS4_LOG_LEVEL" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'DS4_LOG_LEVEL'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "DS4_CONFIG_PATH" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'DS4_CONFIG_PATH'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "dump_config_env_help")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --dump-config-env-help
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "DS4_LOG_LEVEL:" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'DS4_LOG_LEVEL:'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "DS4_CONFIG_PATH:" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'DS4_CONFIG_PATH:'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "help")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --help
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli --help failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "usage:" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli --help output missing 'usage:'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "--dump-config-help" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli --help output missing '--dump-config-help'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "--dump-config-env" _ds4_idx2b)
	if(_ds4_idx2b EQUAL -1)
		message(FATAL_ERROR "ds4_cli --help output missing '--dump-config-env'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "--strict-config" _ds4_idx3)
	if(_ds4_idx3 EQUAL -1)
		message(FATAL_ERROR "ds4_cli --help output missing '--strict-config'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "--smoke-cuda" _ds4_idx4)
	if(_ds4_idx4 EQUAL -1)
		message(FATAL_ERROR "ds4_cli --help output missing '--smoke-cuda'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "ctx_smoke")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --no-cuda --arena-size 16384 --log-ring-entries 4 --smoke-ctx
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli ctx smoke failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "log_ring: ds4_cli smoke ctx" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli ctx smoke stdout missing expected log line\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "cuda_smoke_disabled")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --smoke-cuda
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli cuda smoke failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "cuda build:" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli cuda smoke stdout missing 'cuda build:'\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "cuda: disabled by config" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli cuda smoke stdout missing 'cuda: disabled by config'\nstdout:\n${_ds4_out}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "config_file_dump")
	set(_ds4_cfg "${DS4_TMP_DIR}/ds4_cli_smoke.conf")
	file(WRITE "${_ds4_cfg}" "log_level=debug\nunknown_key=1\nenable_cuda=0\n")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --config "${_ds4_cfg}" --dump-config
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

if(DS4_MODE STREQUAL "config_stdin_dump")
	set(_ds4_cfg "${DS4_TMP_DIR}/ds4_cli_smoke_stdin.conf")
	file(WRITE "${_ds4_cfg}" "log_level=debug\nenable_cuda=0\n")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --config - --dump-config
		INPUT_FILE "${_ds4_cfg}"
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

if(DS4_MODE STREQUAL "config_strict_unknown_reject")
	set(_ds4_cfg "${DS4_TMP_DIR}/ds4_cli_smoke_strict.conf")
	file(WRITE "${_ds4_cfg}" "log_level=debug\nunknown_key=1\nenable_cuda=0\n")
	execute_process(
		COMMAND "${DS4_CLI_PATH}" --strict-config --config "${_ds4_cfg}" --dump-config
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(_ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli strict config unexpectedly succeeded\nstdout:\n${_ds4_out}\nstderr:\n${_ds4_err}")
	endif()
	string(FIND "${_ds4_err}" "unknown keys" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli strict config stderr missing 'unknown keys'\nstderr:\n${_ds4_err}")
	endif()
	string(FIND "${_ds4_err}" "1 unknown keys" _ds4_idx2)
	if(_ds4_idx2 EQUAL -1)
		message(FATAL_ERROR "ds4_cli strict config stderr missing '1 unknown keys'\nstderr:\n${_ds4_err}")
	endif()
	return()
endif()

if(DS4_MODE STREQUAL "config_env_inline_dump")
	execute_process(
		COMMAND "${CMAKE_COMMAND}" -E env "DS4_CONFIG=log_level=debug" "${DS4_CLI_PATH}" --dump-config
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
	return()
endif()

if(DS4_MODE STREQUAL "config_env_path_dump")
	set(_ds4_cfg "${DS4_TMP_DIR}/ds4_cli_smoke_env.conf")
	file(WRITE "${_ds4_cfg}" "log_level=debug\nenable_cuda=0\n")
	execute_process(
		COMMAND "${CMAKE_COMMAND}" -E env "DS4_CONFIG_PATH=${_ds4_cfg}" "${DS4_CLI_PATH}" --dump-config
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

if(DS4_MODE STREQUAL "config_env_inline_over_path")
	set(_ds4_cfg "${DS4_TMP_DIR}/ds4_cli_smoke_env_over_path.conf")
	file(WRITE "${_ds4_cfg}" "log_level=info\nenable_cuda=0\n")
	execute_process(
		COMMAND "${CMAKE_COMMAND}" -E env "DS4_CONFIG_PATH=${_ds4_cfg}" "DS4_CONFIG=log_level=debug" "${DS4_CLI_PATH}" --dump-config
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

if(DS4_MODE STREQUAL "config_env_vars_over_inline")
	execute_process(
		COMMAND "${CMAKE_COMMAND}" -E env "DS4_LOG_LEVEL=error" "DS4_CONFIG=log_level=debug" "${DS4_CLI_PATH}" --dump-config
		OUTPUT_VARIABLE _ds4_out
		ERROR_VARIABLE _ds4_err
		RESULT_VARIABLE _ds4_rv
	)
	if(NOT _ds4_rv EQUAL 0)
		message(FATAL_ERROR "ds4_cli failed: rv=${_ds4_rv}\nstderr:\n${_ds4_err}\nstdout:\n${_ds4_out}")
	endif()
	string(FIND "${_ds4_out}" "log_level=error" _ds4_idx1)
	if(_ds4_idx1 EQUAL -1)
		message(FATAL_ERROR "ds4_cli output missing 'log_level=error'\nstdout:\n${_ds4_out}")
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
