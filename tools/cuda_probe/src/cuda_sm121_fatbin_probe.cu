#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

#define CUDA_PROBE_STR_HELPER(...) #__VA_ARGS__
#define CUDA_PROBE_STR(...) CUDA_PROBE_STR_HELPER(__VA_ARGS__)

__global__ void write_probe(uint32_t *out,uint32_t v)
{
	int32_t tid = ((int32_t)threadIdx.x) + (((int32_t)blockIdx.x) * ((int32_t)blockDim.x));
	if ( tid == 0 )
	{
		out[0] = v;
#if defined(__CUDA_ARCH__)
		out[1] = (uint32_t)__CUDA_ARCH__;
#else
		out[1] = 0;
#endif
	}
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,h_out[2] = {0,0};
	uint32_t v = 0xC0D3CAFEu;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
#if defined(__CUDA_ARCH_LIST__)
	printf("__CUDA_ARCH_LIST__=%s\n",CUDA_PROBE_STR(__CUDA_ARCH_LIST__));
#else
	printf("__CUDA_ARCH_LIST__=(undefined)\n");
#endif
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)(2U * sizeof(uint32_t))),-1,"cudaMalloc");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)(2U * sizeof(uint32_t))),-2,"cudaMemset");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	write_probe<<<1,32>>>(d_out,v);
	rc = cuda_probe_check(cudaGetLastError(),-3,"kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-4,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(&h_out[0],d_out,(size_t)(2U * sizeof(uint32_t)),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	cudaFree(d_out);
	printf("kernel wrote magic=0x%08x __CUDA_ARCH__=%u\n",h_out[0],h_out[1]);
	if ( h_out[0] != v )
		return(-6);
	if ( h_out[1] == 0 )
		return(-7);
	return(0);
}
