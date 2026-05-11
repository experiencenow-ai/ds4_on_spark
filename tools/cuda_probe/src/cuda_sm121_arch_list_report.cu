#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#define STR1(x) #x
#define STR(x) STR1(x)

__global__ void arch_list_report_dummy(uint32_t *out)
{
	if ( ((int32_t)threadIdx.x) == 0 )
		out[0] = 0;
}

int main(int argc,char **argv)
{
	uint32_t *out = 0;
	(void)argc;
	(void)argv;
#if defined(__CUDA_ARCH_LIST__)
	printf("__CUDA_ARCH_LIST__=%s\n",STR(__CUDA_ARCH_LIST__));
#else
	printf("__CUDA_ARCH_LIST__=(missing)\n");
#endif
#if defined(__CUDA_ARCH_SPECIFIC__)
	printf("__CUDA_ARCH_SPECIFIC__=%s\n",STR(__CUDA_ARCH_SPECIFIC__));
#else
	printf("__CUDA_ARCH_SPECIFIC__=(missing)\n");
#endif
#if defined(__CUDA_ARCH_FAMILY_SPECIFIC__)
	printf("__CUDA_ARCH_FAMILY_SPECIFIC__=%s\n",STR(__CUDA_ARCH_FAMILY_SPECIFIC__));
#else
	printf("__CUDA_ARCH_FAMILY_SPECIFIC__=(missing)\n");
#endif
	if ( cudaMalloc((void **)&out,sizeof(uint32_t)) != cudaSuccess )
		return(-1);
	arch_list_report_dummy<<<1,1>>>(out);
	if ( cudaGetLastError() != cudaSuccess )
		return(-2);
	if ( cudaDeviceSynchronize() != cudaSuccess )
		return(-3);
	(void)cudaFree(out);
	return(0);
}
