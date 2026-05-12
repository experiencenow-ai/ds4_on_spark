#include <stdint.h>

#if defined(__CUDA_ARCH__)
#if (__CUDA_ARCH__ != 1210)
#error "compute_121 compile probe: expected __CUDA_ARCH__=1210 (compute_121)"
#endif
#endif

__global__ void compute121_compile_probe(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
	{
#if defined(__CUDA_ARCH__)
		out[0] = (uint32_t)__CUDA_ARCH__;
#else
		out[0] = 0;
#endif
	}
}

