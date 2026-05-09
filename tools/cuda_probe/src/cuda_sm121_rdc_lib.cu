#include <stdint.h>
extern "C" __device__ __noinline__ uint32_t cuda_sm121_rdc_magic(uint32_t x)
{
	return((x ^ 0xA5A5A5A5u) + 1u);
}

