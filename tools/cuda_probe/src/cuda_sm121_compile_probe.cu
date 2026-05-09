#include <stdint.h>

__global__ void sm121_compile_probe(uint32_t *out)
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

