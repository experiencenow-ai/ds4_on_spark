#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

#define STR1(x) #x
#define STR(x) STR1(x)

__global__ void arch_list_report_dummy(void)
{
}

int main(int argc,char **argv)
{
	int32_t rc = 0;
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
	arch_list_report_dummy<<<1,1>>>();
	rc = cuda_probe_check(cudaGetLastError(),-1,"kernel launch");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaDeviceSynchronize(),-2,"cudaDeviceSynchronize");
	if ( rc != 0 )
		return(rc);
	return(0);
}
