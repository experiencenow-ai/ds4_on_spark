function(ds4_target_warnings target werror)
	if(CMAKE_C_COMPILER_ID MATCHES "Clang|AppleClang|GNU")
		target_compile_options(${target} PRIVATE
			$<$<COMPILE_LANGUAGE:C>:-Wall>
			$<$<COMPILE_LANGUAGE:C>:-Wextra>
			$<$<COMPILE_LANGUAGE:C>:-Wpedantic>
			$<$<COMPILE_LANGUAGE:C>:-Wshadow>
			$<$<COMPILE_LANGUAGE:C>:-Wconversion>
			$<$<COMPILE_LANGUAGE:C>:-Wstrict-prototypes>
			$<$<COMPILE_LANGUAGE:C>:-Wmissing-prototypes>
		)
		if(werror)
			target_compile_options(${target} PRIVATE $<$<COMPILE_LANGUAGE:C>:-Werror>)
		endif()
	endif()
endfunction()
