function(ds4_target_warnings target werror)
	if(CMAKE_C_COMPILER_ID MATCHES "Clang|AppleClang|GNU")
		target_compile_options(${target} PRIVATE
			-Wall
			-Wextra
			-Wpedantic
			-Wshadow
			-Wconversion
			-Wstrict-prototypes
			-Wmissing-prototypes
		)
		if(werror)
			target_compile_options(${target} PRIVATE -Werror)
		endif()
	endif()
endfunction()
