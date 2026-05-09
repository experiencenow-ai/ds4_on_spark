#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

extern "C" __device__ uint32_t cuda_sm121_rdc_magic(uint32_t x);

__global__ void cuda_sm121_rdc_kernel(uint32_t *out,uint32_t in)
{
	int32_t tid = ((int32_t)threadIdx.x) + (((int32_t)blockIdx.x) * ((int32_t)blockDim.x));
	if ( tid == 0 )
		out[0] = cuda_sm121_rdc_magic(in);
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,h_out = 0;
	uint32_t in = 0x12345678u;
	uint32_t expect = ((in ^ 0xA5A5A5A5u) + 1u);
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint32_t)),-1,"cudaMalloc");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)sizeof(uint32_t)),-2,"cudaMemset");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	cuda_sm121_rdc_kernel<<<1,32>>>(d_out,in);
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
	printf("rdc_probe in=0x%08x out=0x%08x expect=0x%08x\n",in,h_out,expect);
	if ( h_out != expect )
		return(-6);
	return(0);
}

