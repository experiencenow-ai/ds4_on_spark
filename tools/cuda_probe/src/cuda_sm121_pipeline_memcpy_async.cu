#include <stdint.h>
#include <stdio.h>

#include <cuda_pipeline_primitives.h>
#include <cuda_runtime.h>

#include "cuda_probe_util.h"

__global__ void pipeline_memcpy_async_u4(const uint4 *in,uint4 *out)
{
	__shared__ uint4 sh[1];
	if ( blockIdx.x != 0 || threadIdx.x != 0 )
		return;
	__pipeline_memcpy_async(&sh[0],&in[0],(size_t)16);
	__pipeline_commit();
	__pipeline_wait_prior((size_t)0);
	out[0] = sh[0];
}

int main(int argc,char **argv)
{
	uint4 *d_in = 0,*d_out = 0;
	uint4 h_in,h_out;
	int32_t rc = 0;
	(void)argc;
	(void)argv;
	cuda_probe_print_versions();
	h_in = make_uint4(0x11111111u,0x22222222u,0x33333333u,0x44444444u);
	h_out = make_uint4(0,0,0,0);
	rc = cuda_probe_check(cudaMalloc((void **)&d_in,(size_t)sizeof(uint4)),-1,"cudaMalloc(d_in)");
	if ( rc != 0 )
		return(rc);
	rc = cuda_probe_check(cudaMalloc((void **)&d_out,(size_t)sizeof(uint4)),-2,"cudaMalloc(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(d_in,&h_in,(size_t)sizeof(uint4),cudaMemcpyHostToDevice),-3,"cudaMemcpy(H2D)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemset(d_out,0,(size_t)sizeof(uint4)),-4,"cudaMemset(d_out)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	pipeline_memcpy_async_u4<<<1,32>>>(d_in,d_out);
	rc = cuda_probe_check(cudaGetLastError(),-5,"kernel launch");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaDeviceSynchronize(),-6,"cudaDeviceSynchronize");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	rc = cuda_probe_check(cudaMemcpy(&h_out,d_out,(size_t)sizeof(uint4),cudaMemcpyDeviceToHost),-7,"cudaMemcpy(D2H)");
	if ( rc != 0 )
	{
		cudaFree(d_out);
		cudaFree(d_in);
		return(rc);
	}
	cudaFree(d_out);
	cudaFree(d_in);
	printf("pipeline_memcpy_async out=%08x %08x %08x %08x\n",h_out.x,h_out.y,h_out.z,h_out.w);
	if ( (h_out.x != h_in.x) || (h_out.y != h_in.y) || (h_out.z != h_in.z) || (h_out.w != h_in.w) )
		return(-8);
	return(0);
}

