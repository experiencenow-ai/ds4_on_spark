#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void write_probe(uint32_t *out,uint32_t v)
{
	int32_t tid = ((int32_t)threadIdx.x) + (((int32_t)blockIdx.x) * ((int32_t)blockDim.x));
	if ( tid == 0 )
		out[0] = v;
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,h_out = 0;
	uint32_t v = 0xC0D3CAFEu;
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
	rc = cuda_probe_check(cudaMemcpy(&h_out,d_out,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		return(rc);
	}
	cudaFree(d_out);
	printf("kernel wrote 0x%08x\n",h_out);
	if ( h_out != v )
		return(-6);
	return(0);
}
