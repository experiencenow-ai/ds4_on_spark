function(ds4_target_sanitizers target enable_asan enable_ubsan)
	if(NOT (CMAKE_C_COMPILER_ID MATCHES "Clang|AppleClang|GNU"))
		return()
	endif()

	set(_ds4_san_list "")
	if(enable_asan)
		list(APPEND _ds4_san_list address)
	endif()
	if(enable_ubsan)
		list(APPEND _ds4_san_list undefined)
	endif()
	if(NOT _ds4_san_list)
		return()
	endif()

	string(REPLACE ";" "," _ds4_sans "${_ds4_san_list}")
	target_compile_options(${target} PUBLIC
		$<$<COMPILE_LANGUAGE:C>:-fno-omit-frame-pointer;-fsanitize=${_ds4_sans}>
	)
	target_link_options(${target} PUBLIC -fsanitize=${_ds4_sans})
endfunction()
