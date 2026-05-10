function(ds4_target_cuda target)
	find_package(CUDAToolkit REQUIRED)
	target_sources(${target} PRIVATE
		src/ds4_cuda.cu
	)
	target_compile_definitions(${target} PUBLIC DS4_HAS_CUDA=1)
	set_source_files_properties(src/ds4_cuda.cu PROPERTIES LANGUAGE CUDA)
	set_target_properties(${target} PROPERTIES CUDA_SEPARABLE_COMPILATION OFF)

	if(CMAKE_CUDA_COMPILER_ID MATCHES "NVIDIA")
		target_compile_options(${target} PRIVATE $<$<COMPILE_LANGUAGE:CUDA>:-lineinfo>)
	endif()

	target_link_libraries(${target} PUBLIC CUDA::cudart)
endfunction()
