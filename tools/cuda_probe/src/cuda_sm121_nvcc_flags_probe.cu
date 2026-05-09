#include <stdint.h>
#include <stdio.h>

#include <cuda_runtime.h>

#include "cuda_probe_util.h"

static __global__ void nvcc_flags_probe(uint32_t *out)
{
	constexpr uint32_t magic = 0x12345678u;
	if ( out == 0 )
		return;
	auto add1 = [=] __device__ (uint32_t x)
	{
		return(x + 1u);
	};
	if ( (int32_t)blockIdx.x == 0 && (int32_t)threadIdx.x == 0 )
		out[0] = add1(magic);
}

int main(int argc,char **argv)
{
	uint32_t *d_out = 0,out = 0;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	do
	{
		rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint32_t)),-1,"cudaMalloc(d_out)");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)sizeof(uint32_t)),-2,"cudaMemset(d_out)");
		if ( rc != 0 )
			break;
		nvcc_flags_probe<<<1,32>>>(d_out);
		rc = cuda_probe_check(cudaGetLastError(),-3,"nvcc_flags_probe launch");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaDeviceSynchronize(),-4,"cudaDeviceSynchronize");
		if ( rc != 0 )
			break;
		rc = cuda_probe_check(cudaMemcpy(&out,d_out,(size_t)sizeof(uint32_t),cudaMemcpyDeviceToHost),-5,"cudaMemcpy(D2H out)");
		if ( rc != 0 )
			break;
	} while (0);
	if ( d_out != 0 )
		cudaFree(d_out);
	if ( rc != 0 )
		return(rc);
	if ( out != 0x12345679u )
	{
		fprintf(stderr,"nvcc_flags_probe bad out=0x%08x\n",out);
		return(-6);
	}
	printf("nvcc_flags_probe ok out=0x%08x\n",out);
	return(0);
}

