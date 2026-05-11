#define STR1(x) #x
#define STR(x) STR1(x)

#if defined(__CUDA_ARCH_LIST__)
#pragma message("DS4_CUDA_ARCH_LIST=" STR(__CUDA_ARCH_LIST__))
#else
#pragma message("DS4_CUDA_ARCH_LIST=(missing)")
#endif

#if defined(__CUDA_ARCH__)
#pragma message("DS4_CUDA_ARCH=" STR(__CUDA_ARCH__))
#else
#pragma message("DS4_CUDA_ARCH=(missing)")
#endif

#if defined(__CUDA_ARCH_SPECIFIC__)
#pragma message("DS4_CUDA_ARCH_SPECIFIC=" STR(__CUDA_ARCH_SPECIFIC__))
#else
#pragma message("DS4_CUDA_ARCH_SPECIFIC=(missing)")
#endif

#if defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
#pragma message("DS4_CUDA_ARCH_FAMILY_SPECIFIC=" STR(__CUDA_ARCH_FAMILY_SPECIFIC__))
#else
#pragma message("DS4_CUDA_ARCH_FAMILY_SPECIFIC=(missing)")
#endif

int cuda_sm121_arch_list_compile_probe_dummy(void)
{
	return(0);
}
