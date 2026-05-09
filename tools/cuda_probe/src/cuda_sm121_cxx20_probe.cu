#include <stdint.h>
#include <stdio.h>

#include <bit>
#include <span>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void cxx20_probe_arch(uint32_t *out)
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

int main(int argc,char **argv)
{
	float x = 1.25f;
	uint32_t bits = std::bit_cast<uint32_t>(x);
	int32_t arr[4] = {1,2,3,4};
	std::span<int32_t,4> s(arr);
	int32_t i = 0,rc = 0,sum = 0;
	uint32_t *d_out = 0,arch = 0;
	(void)argc;
	(void)argv;
	for (i=0; i<4; i++)
		sum += s[i];
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint32_t)),-1,"cudaMalloc(d_out)");
	if ( rc != 0 )
		return(rc);
	cxx20_probe_arch<<<1,32>>>(d_out);
	rc = cuda_probe_check(cudaGetLastError(),-2,"cxx20_probe kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-3,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(&arch,d_out,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-4,"cudaMemcpy(d_out D2H)");
	cudaFree(d_out);
	if ( rc != 0 )
		return(rc);
	printf("cxx20_probe ok bits=0x%08x sum=%d __CUDA_ARCH__=%u\n",bits,sum,arch);
	return(0);
}

