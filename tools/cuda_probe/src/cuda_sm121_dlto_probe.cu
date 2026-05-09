#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__device__ __noinline__ uint32_t dlto_mix_u32(uint32_t x)
{
	x ^= 0xA5A5A5A5u;
	x = (x * 1664525u) + 1013904223u;
	x ^= (x >> 16);
	x *= 2246822519u;
	x ^= (x >> 13);
	x *= 3266489917u;
	x ^= (x >> 16);
	return(x);
}

static uint32_t host_mix_u32(uint32_t x)
{
	x ^= 0xA5A5A5A5u;
	x = (x * 1664525u) + 1013904223u;
	x ^= (x >> 16);
	x *= 2246822519u;
	x ^= (x >> 13);
	x *= 3266489917u;
	x ^= (x >> 16);
	return(x);
}

__global__ void dlto_kernel(uint32_t *out,uint32_t in)
{
	int32_t tid = ((int32_t)threadIdx.x) + (((int32_t)blockIdx.x) * ((int32_t)blockDim.x));
	if ( tid == 0 )
		out[0] = dlto_mix_u32(in);
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,h_out = 0,in = 0x12345678u,expect = 0;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	expect = host_mix_u32(in);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint32_t)),-1,"cudaMalloc");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)sizeof(uint32_t)),-2,"cudaMemset");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	dlto_kernel<<<1,32>>>(d_out,in);
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
	rc = cuda_probe_check(cudaMemcpy(&h_out,d_out,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	cudaFree(d_out);
	printf("dlto_probe in=0x%08x out=0x%08x expect=0x%08x\n",in,h_out,expect);
	if ( h_out != expect )
		return(-6);
	return(0);
}
